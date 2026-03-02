#!/usr/bin/env python3
"""
Fetch UI test workflow run data from GitHub Actions and compute health metrics.

Outputs a structured JSON report covering pass rates, flakiness scores, and
per-PR test results for the given look-back window.

Usage:
    python fetch_ui_test_runs.py [--owner OWNER] [--repo REPO] [--days DAYS]
                                 [--workflow-name NAME] [--output PATH]

Environment Variables:
    GITHUB_ACCESS_TOKEN or GITHUB_PAT: GitHub personal access token with repo and actions:read scopes
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Auth & HTTP helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    token = os.environ.get("GITHUB_ACCESS_TOKEN") or os.environ.get("GITHUB_PAT")
    if not token:
        print("ERROR: Set GITHUB_ACCESS_TOKEN or GITHUB_PAT environment variable.", file=sys.stderr)
        sys.exit(1)
    return token


def github_get(url: str, token: str, params: dict | None = None) -> dict | list:
    """Perform a GitHub REST API GET request and return parsed JSON."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                remaining = resp.headers.get("X-RateLimit-Remaining")
                if remaining is not None and int(remaining) < 10:
                    print("Rate limit nearly exhausted — sleeping 60s...", file=sys.stderr)
                    time.sleep(60)
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code == 403:
                wait = 60 * (attempt + 1)
                print(f"Rate limited (HTTP {exc.code}), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Failed to GET {url} after 3 attempts")


def github_get_all_pages(base_url: str, token: str, params: dict | None = None, max_items: int = 0) -> list:
    """Fetch all pages of a GitHub list endpoint.

    Args:
        max_items: Stop after collecting this many items (0 = no limit).
    """
    all_items: list = []
    p = dict(params or {})
    p.setdefault("per_page", 100)
    page = 1
    while True:
        p["page"] = page
        data = github_get(base_url, token, params=p)
        items = data if isinstance(data, list) else data.get("workflow_runs") or data.get("jobs") or data.get("workflows") or data.get("pull_requests") or []
        if not items:
            break
        all_items.extend(items)
        if max_items > 0 and len(all_items) >= max_items:
            all_items = all_items[:max_items]
            break
        if len(items) < p["per_page"]:
            break
        page += 1
    return all_items


# ---------------------------------------------------------------------------
# Step 1: Resolve workflow ID
# ---------------------------------------------------------------------------

def get_workflow_id(owner: str, repo: str, workflow_name: str, token: str) -> int:
    print(f"Resolving workflow ID for '{workflow_name}'...", file=sys.stderr)
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows"
    data = github_get(url, token, params={"per_page": 100})
    workflows = data.get("workflows", [])
    for wf in workflows:
        if wf["name"] == workflow_name:
            print(f"  Found workflow ID: {wf['id']}", file=sys.stderr)
            return wf["id"]
    names = [wf["name"] for wf in workflows]
    print(f"ERROR: Workflow '{workflow_name}' not found in {owner}/{repo}.", file=sys.stderr)
    print(f"Available workflows: {names}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Step 2: Fetch workflow runs
# ---------------------------------------------------------------------------

def fetch_workflow_runs(owner: str, repo: str, wf_id: int, since_iso: str, token: str) -> list:
    print(f"Fetching workflow runs since {since_iso}...", file=sys.stderr)
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{wf_id}/runs"
    all_runs: list = []
    page = 1
    while True:
        data = github_get(url, token, params={
            "created": f">{since_iso}",
            "per_page": 100,
            "page": page,
        })
        runs = data.get("workflow_runs", [])
        if not runs:
            break
        all_runs.extend(runs)
        total = data.get("total_count", 0)
        print(f"  Fetched {len(all_runs)}/{total} runs...", file=sys.stderr)
        if len(all_runs) >= total or len(runs) < 100:
            break
        page += 1
    print(f"  Total runs fetched: {len(all_runs)}", file=sys.stderr)
    return all_runs


# ---------------------------------------------------------------------------
# Step 3: Fetch jobs per run attempt
# ---------------------------------------------------------------------------

JOB_RE = re.compile(r"UI Test \((\w+),\s*([\d.]+),\s*(\w+)\)")


def parse_job_name(name: str) -> tuple[str, str, str] | None:
    """Extract (ide_type, ide_version, test_class) from a job name."""
    m = JOB_RE.match(name)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def fetch_jobs_for_run(owner: str, repo: str, run_id: int, attempt: int, token: str) -> list:
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
    data = github_get(url, token, params={"per_page": 100})
    return data.get("jobs", [])


# ---------------------------------------------------------------------------
# Step 4: Fetch recent PRs for SHA cross-reference
# ---------------------------------------------------------------------------

def _pr_info_from_api(data: dict) -> dict:
    """Extract standard PR info fields from a GitHub API PR response object."""
    return {
        "pr_number": data.get("number"),
        "pr_title": data.get("title", ""),
        "pr_url": data.get("html_url", ""),
        "pr_author": data.get("user", {}).get("login", ""),
    }


def fetch_recent_prs(owner: str, repo: str, token: str) -> dict:
    """Return a dict mapping head_sha -> PR info.

    Fetches up to 500 recently-updated PRs (open and closed) regardless of age,
    so that older closed PRs whose SHAs appear in recent workflow runs are still
    resolved to their title and author.
    """
    print("Fetching recent PRs for SHA cross-reference...", file=sys.stderr)
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    prs = github_get_all_pages(url, token, params={
        "state": "all",
        "sort": "updated",
        "direction": "desc",
        "per_page": 100,
    }, max_items=500)
    sha_to_pr: dict = {}
    for pr in prs:
        sha = pr.get("head", {}).get("sha")
        if sha:
            sha_to_pr[sha] = _pr_info_from_api(pr)
    print(f"  Found {len(sha_to_pr)} recent PR SHAs", file=sys.stderr)
    return sha_to_pr


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def enrich_pr_metadata(entries: list, owner: str, repo: str, token: str,
                       shared_cache: dict | None = None) -> None:
    """Fill in missing pr_title / pr_author in-place for any entry that has a
    pr_number but no title/author (e.g. runs whose commit SHA was not the PR's
    current head SHA at fetch time).

    Makes one API call per unique missing PR number. Pass ``shared_cache`` to
    share already-fetched results across multiple calls and avoid duplicate
    API requests for the same PR number.
    """
    if shared_cache is None:
        shared_cache = {}

    missing = {
        e["pr_number"]
        for e in entries
        if e.get("pr_number") and not e.get("pr_title") and not e.get("pr_author")
        and e["pr_number"] not in shared_cache
    }

    if missing:
        print(f"Enriching metadata for {len(missing)} PR(s) with missing title/author...", file=sys.stderr)
        for pr_number in missing:
            url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
            try:
                data = github_get(url, token)
                shared_cache[pr_number] = _pr_info_from_api(data)
            except Exception as exc:
                print(f"  Warning: could not fetch PR #{pr_number}: {exc}", file=sys.stderr)

    for e in entries:
        num = e.get("pr_number")
        if num and num in shared_cache and not e.get("pr_title") and not e.get("pr_author"):
            e.update(shared_cache[num])


def resolve_pr_info(run: dict, sha_to_pr: dict) -> dict:
    """Return PR info dict for a run, falling back to sha_to_pr lookup."""
    sha = run.get("head_sha", "")
    cached = sha_to_pr.get(sha, {})
    prs = run.get("pull_requests") or []
    if prs:
        pr = prs[0]
        fallback_url = pr.get("url", "").replace("api.github.com/repos", "github.com").replace("/pulls/", "/pull/")
        return {
            "pr_number": pr.get("number"),
            "pr_title": cached.get("pr_title", ""),
            "pr_url": cached.get("pr_url", fallback_url),
            "pr_author": cached.get("pr_author", ""),
        }
    if cached:
        return cached
    return {"pr_number": None, "pr_title": "", "pr_url": "", "pr_author": ""}


def classify_retry_pattern(conclusions: list[str | None]) -> tuple[str, int]:
    """
    conclusions: sorted by run_attempt asc.
    Returns (status, retries_needed):
      - status: passed_first | passed_after_retry | never_passed | in_progress
      - retries_needed: 0 if passed_first, N if passed after N retries, -1 otherwise
    """
    if not conclusions:
        return "in_progress", -1
    if conclusions[0] == "success":
        return "passed_first", 0
    for i, c in enumerate(conclusions[1:], start=1):
        if c == "success":
            return "passed_after_retry", i  # i retries needed (attempt i+1 succeeded)
    if conclusions[-1] in (None, "in_progress", "queued", "waiting"):
        return "in_progress", -1
    return "never_passed", -1


def safe_pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


def safe_score(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def aggregate_results(runs: list, sha_to_pr: dict, owner: str, repo: str, token: str) -> dict:
    """
    Core aggregation: group runs by (head_sha, test_key), classify retry patterns,
    and compute all metrics.
    """
    # Structure: groups[(head_sha, ide_type, ide_version, test_class)] = list of {run_attempt, conclusion, run_url}
    groups: dict = defaultdict(list)
    sha_pr_map: dict = {}  # head_sha -> pr_info

    total_runs = len(runs)
    print(f"Fetching jobs for {total_runs} runs...", file=sys.stderr)

    for i, run in enumerate(runs, 1):
        run_id = run["id"]
        attempt = run.get("run_attempt", 1)
        sha = run.get("head_sha", "")
        conclusion = run.get("conclusion")  # None if in progress
        run_url = run.get("html_url", "")

        pr_info = resolve_pr_info(run, sha_to_pr)
        if sha not in sha_pr_map:
            sha_pr_map[sha] = pr_info

        if (i % 10) == 0 or i == total_runs:
            print(f"  Processing run {i}/{total_runs}...", file=sys.stderr)

        # GitHub's list-runs API only returns the *latest* attempt of each run.
        # To see the full retry history we must also fetch jobs for every earlier
        # attempt (1 … attempt-1) individually.
        attempts_to_fetch = list(range(1, attempt + 1))

        parsed_any = False
        for att in attempts_to_fetch:
            try:
                jobs = fetch_jobs_for_run(owner, repo, run_id, att, token)
            except Exception as exc:
                print(f"  Warning: could not fetch jobs for run {run_id} attempt {att}: {exc}", file=sys.stderr)
                jobs = []

            for job in jobs:
                key_tuple = parse_job_name(job.get("name", ""))
                if key_tuple is None:
                    continue
                ide_type, ide_version, test_class = key_tuple
                group_key = (sha, ide_type, ide_version, test_class)
                groups[group_key].append({
                    "run_attempt": att,
                    "conclusion": job.get("conclusion") or (conclusion if att == attempt else "failure"),
                    "run_url": run_url,
                })
                parsed_any = True

        # If no test jobs parsed but run has a conclusion, still record at SHA level
        if not parsed_any and sha:
            pass  # orphaned run — counted in total_workflow_runs but not per-test

    # --- Per-(sha, test_key) classification ---
    # Deduplicate: for same (sha, test_key, attempt), keep only once
    for gk in groups:
        seen_attempts = {}
        for entry in groups[gk]:
            a = entry["run_attempt"]
            if a not in seen_attempts:
                seen_attempts[a] = entry
        groups[gk] = sorted(seen_attempts.values(), key=lambda e: e["run_attempt"])

    # --- Classify each group ---
    # classified[(sha, test_key)] = {status, retries_needed, attempts, latest_run_url}
    classified: dict = {}
    total_retry_attempts = 0  # groups that had at least one run_attempt > 1
    for group_key, entries in groups.items():
        sha, ide_type, ide_version, test_class = group_key
        conclusions = [e["conclusion"] for e in entries]
        status, retries_needed = classify_retry_pattern(conclusions)
        classified[group_key] = {
            "status": status,
            "retries_needed": retries_needed,  # 0=passed_first, N=retries, -1=n/a
            "attempts": len(entries),
            "latest_run_url": entries[-1]["run_url"],
        }
        if any(e["run_attempt"] > 1 for e in entries):
            total_retry_attempts += 1

    # --- Aggregate per test class ---
    # retry_counts[(ide_type, ide_version, test_class)][N] = count of instances that needed N retries to pass
    test_class_counts: dict = defaultdict(lambda: {"passed_first": 0, "passed_after_retry": 0, "never_passed": 0, "in_progress": 0})
    retry_dist: dict = defaultdict(lambda: defaultdict(int))  # tk -> {retries_needed: count}
    for (sha, ide_type, ide_version, test_class), info in classified.items():
        tk = (ide_type, ide_version, test_class)
        test_class_counts[tk][info["status"]] += 1
        if info["status"] == "passed_after_retry" and info["retries_needed"] > 0:
            retry_dist[tk][info["retries_needed"]] += 1

    per_test_class = []
    for (ide_type, ide_version, test_class), counts in sorted(test_class_counts.items()):
        pf = counts["passed_first"]
        par = counts["passed_after_retry"]
        np_ = counts["never_passed"]
        ip = counts["in_progress"]
        total_instances = pf + par + np_ + ip
        total_resolved = pf + par + np_
        tk = (ide_type, ide_version, test_class)
        # Build retry distribution: {"1": N, "2": N, "3+": N}
        dist_raw = retry_dist.get(tk, {})
        retry_distribution = {}
        for n in sorted(dist_raw.keys()):
            key = str(n) if n <= 2 else "3+"
            retry_distribution[key] = retry_distribution.get(key, 0) + dist_raw[n]
        entry = {
            "ide_type": ide_type,
            "ide_version": ide_version,
            "test_class": test_class,
            "total_instances": total_instances,
            "passed_first_attempt": pf,
            "passed_after_retry": par,
            "retry_distribution": retry_distribution,  # e.g. {"1": 3, "2": 1, "3+": 1}
            "never_passed": np_,
            "in_progress": ip,
            "first_attempt_pass_rate_pct": safe_pct(pf, total_resolved),
            "any_attempt_pass_rate_pct": safe_pct(pf + par, total_resolved),
            "flakiness_score": safe_score(par, total_resolved),
        }
        per_test_class.append(entry)

    # --- Aggregate per PR ---
    # Group classified entries by sha first
    sha_entries: dict = defaultdict(list)
    for (sha, ide_type, ide_version, test_class), info in classified.items():
        sha_entries[sha].append({
            "ide_type": ide_type,
            "ide_version": ide_version,
            "test_class": test_class,
            **info,
        })

    per_pr = []
    for sha, entries in sha_entries.items():
        pr_info = sha_pr_map.get(sha, {"pr_number": None, "pr_title": "", "pr_url": "", "pr_author": ""})
        counts = {"passed_first": 0, "passed_after_retry": 0, "never_passed": 0, "in_progress": 0}
        for e in entries:
            counts[e["status"]] += 1

        pf = counts["passed_first"]
        par = counts["passed_after_retry"]
        np_ = counts["never_passed"]
        ip = counts["in_progress"]

        if ip > 0:
            overall_status = "in_progress"
        elif np_ > 0:
            overall_status = "has_failures"
        elif par > 0:
            overall_status = "flaky_but_passing"
        else:
            overall_status = "all_green"

        test_results = sorted(
            [
                {
                    "ide_type": e["ide_type"],
                    "ide_version": e["ide_version"],
                    "test_class": e["test_class"],
                    "status": e["status"],
                    "attempts": e["attempts"],
                    "retries_needed": e["retries_needed"],  # 0, 1, 2, … or -1 if n/a
                    "latest_run_url": e["latest_run_url"],
                }
                for e in entries
            ],
            key=lambda x: (x["ide_type"], x["ide_version"], x["test_class"]),
        )

        per_pr.append({
            "pr_number": pr_info["pr_number"],
            "pr_title": pr_info["pr_title"],
            "pr_url": pr_info["pr_url"],
            "pr_author": pr_info["pr_author"],
            "head_sha": sha,
            "total_test_instances": len(entries),
            "passed_first_attempt": pf,
            "passed_after_retry": par,
            "never_passed": np_,
            "in_progress": ip,
            "overall_status": overall_status,
            "test_results": test_results,
        })

    # Sort per_pr: has_failures first, then flaky_but_passing, then all_green, then in_progress
    status_order = {"has_failures": 0, "flaky_but_passing": 1, "all_green": 2, "in_progress": 3}
    per_pr.sort(key=lambda p: (status_order.get(p["overall_status"], 9), -(p["pr_number"] or 0)))

    # --- Overall aggregate ---
    total_pf = sum(c["passed_first_attempt"] for c in per_test_class)
    total_par = sum(c["passed_after_retry"] for c in per_test_class)
    total_np = sum(c["never_passed"] for c in per_test_class)
    total_ip = sum(c["in_progress"] for c in per_test_class)
    total_instances = total_pf + total_par + total_np + total_ip
    total_resolved = total_pf + total_par + total_np

    aggregate = {
        "total_pr_test_instances": total_instances,
        "passed_first_attempt": total_pf,
        "passed_after_retry": total_par,
        "never_passed": total_np,
        "in_progress": total_ip,
        "total_retry_attempts": total_retry_attempts,
        "pass_rate_any_attempt_pct": safe_pct(total_pf + total_par, total_resolved),
        "first_attempt_pass_rate_pct": safe_pct(total_pf, total_resolved),
        "retry_success_rate_pct": safe_pct(total_par, total_par + total_np),
        "never_passed_rate_pct": safe_pct(total_np, total_resolved),
    }

    # --- Top flaky tests ---
    top_flaky = [
        {
            "ide_type": tc["ide_type"],
            "ide_version": tc["ide_version"],
            "test_class": tc["test_class"],
            "passed_after_retry": tc["passed_after_retry"],
            "retry_distribution": tc["retry_distribution"],  # {"1": N, "2": N, "3+": N}
            "never_passed": tc["never_passed"],
            "total_instances": tc["total_instances"],
            "flakiness_score": tc["flakiness_score"],
        }
        for tc in per_test_class
        if tc["passed_after_retry"] >= 1
    ]
    top_flaky.sort(key=lambda x: (-x["passed_after_retry"], -x["flakiness_score"]))

    # --- PRs with persistent failures ---
    prs_with_failures = []
    for pr in per_pr:
        if pr["overall_status"] == "has_failures":
            failed_tests = [
                {
                    "ide_type": tr["ide_type"],
                    "ide_version": tr["ide_version"],
                    "test_class": tr["test_class"],
                    "attempts": tr["attempts"],
                    "latest_run_url": tr["latest_run_url"],
                }
                for tr in pr["test_results"]
                if tr["status"] == "never_passed"
            ]
            prs_with_failures.append({
                "pr_number": pr["pr_number"],
                "pr_title": pr["pr_title"],
                "pr_url": pr["pr_url"],
                "pr_author": pr["pr_author"],
                "failed_tests": failed_tests,
            })

    return {
        "aggregate": aggregate,
        "per_test_class": per_test_class,
        "per_pr": per_pr,
        "top_flaky_tests": top_flaky,
        "prs_with_persistent_failures": prs_with_failures,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch UI test health data from GitHub Actions.")
    parser.add_argument("--owner", default="microsoft", help="Repository owner (default: microsoft)")
    parser.add_argument("--repo", default="copilot-intellij", help="Repository name (default: copilot-intellij)")
    parser.add_argument("--days", type=int, default=3, help="Look-back window in days (default: 3)")
    parser.add_argument("--workflow-name", default="UI Test New", help="Exact workflow name (default: 'UI Test New')")
    parser.add_argument("--output", default="ui_test_health.json", help="Output JSON file path")
    args = parser.parse_args()

    token = get_token()

    now = datetime.now(tz=timezone.utc)
    since_dt = now - timedelta(days=args.days)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Step 1: Resolve workflow ID
    wf_id = get_workflow_id(args.owner, args.repo, args.workflow_name, token)

    # Step 2: Fetch all workflow runs
    runs = fetch_workflow_runs(args.owner, args.repo, wf_id, since_iso, token)

    if not runs:
        print(f"Warning: No workflow runs found in the past {args.days} day(s).", file=sys.stderr)

    # Step 3+4: Fetch PRs for cross-reference, then jobs per run (inside aggregate)
    sha_to_pr = fetch_recent_prs(args.owner, args.repo, token)

    # Aggregate
    result = aggregate_results(runs, sha_to_pr, args.owner, args.repo, token)

    # Enrich any per_pr / prs_with_persistent_failures entries that still lack title/author.
    # A shared cache ensures each missing PR number is fetched only once across both lists.
    enrich_cache: dict = {}
    enrich_pr_metadata(result["per_pr"], args.owner, args.repo, token, enrich_cache)
    enrich_pr_metadata(result["prs_with_persistent_failures"], args.owner, args.repo, token, enrich_cache)

    # Build final report
    report = {
        "metadata": {
            "owner": args.owner,
            "repo": args.repo,
            "workflow_name": args.workflow_name,
            "since": since_iso,
            "until": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "days": args.days,
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_workflow_runs": len(runs),
            "total_prs_analyzed": len([p for p in result["per_pr"] if p["pr_number"] is not None]),
        },
        **result,
    }

    # Write output
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    pr_count = report["metadata"]["total_prs_analyzed"]
    run_count = report["metadata"]["total_workflow_runs"]
    pass_rate = report["aggregate"]["pass_rate_any_attempt_pct"]
    print(f"Saved report to {args.output} — {pr_count} PRs, {run_count} workflow runs, {pass_rate}% pass rate (any attempt)")


if __name__ == "__main__":
    main()
