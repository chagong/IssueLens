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
from collections import Counter, defaultdict
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


def _github_api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_get(url: str, token: str, params: dict | None = None) -> dict | list:
    """Perform a GitHub REST API GET request and return parsed JSON."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers=_github_api_headers(token),
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
            if exc.code == 404:
                body = exc.read().decode("utf-8", errors="replace")
                print(f"HTTP 404 Not Found: {url}", file=sys.stderr)
                print(f"Response body: {body}", file=sys.stderr)
                token_len = len(token) if token else 0
                print(f"Token length: {token_len}", file=sys.stderr)
            if exc.code == 429 or exc.code == 403:
                retry_after = exc.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 60 * (attempt + 1)
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
# Step 3b: Fetch and parse job logs for failure reasons
# ---------------------------------------------------------------------------

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Raise immediately on any redirect so we can capture the Location header."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(newurl, code, msg, headers, fp)


def fetch_job_log(owner: str, repo: str, job_id: int, token: str) -> str | None:
    """Fetch the plain-text log for a job via the GitHub API redirect.

    The logs endpoint issues a 302 to a pre-signed blob URL (S3/Azure).
    That URL must be fetched *without* the Authorization header or the
    cloud storage service will reject the request with 400/403.
    Returns the decoded log text, or None if the log could not be fetched.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/jobs/{job_id}/logs"
    req = urllib.request.Request(url, headers=_github_api_headers(token))
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(req, timeout=30):
            pass  # non-redirect response: no log content available at this URL
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            redirect_url = exc.headers.get("Location")
            if not redirect_url:
                return None
            try:
                with urllib.request.urlopen(redirect_url, timeout=60) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception as fetch_exc:
                print(f"  Warning: could not fetch log blob for job {job_id}: {fetch_exc}", file=sys.stderr)
                return None
        print(f"  Warning: HTTP {exc.code} fetching log for job {job_id}", file=sys.stderr)
    except Exception as exc:
        print(f"  Warning: could not fetch log for job {job_id}: {exc}", file=sys.stderr)
    return None


_FAILED_LINE_RE = re.compile(r"(\w[\w$]*)\s*>\s*(.+?)\(\)\s+FAILED", re.MULTILINE)
_EXCEPTION_LINE_RE = re.compile(r"^\s+([\w$][\w$.]*(?:Error|Exception|Failure))\b(.*)", re.MULTILINE)
# GitHub Actions prepends a timestamp to every log line: "2026-03-05T05:46:43.000Z "
# Strip these before applying regexes so that "^\s+" can match correctly.
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z ", re.MULTILINE)


def extract_all_failure_reasons(log_text: str, test_class: str) -> list[dict]:
    """Parse all FAILED blocks in a CI log for the given test_class.

    A single job log can contain multiple FAILED blocks (one per failed test
    method).  Returns a list with one dict per block — never None, may be empty.

    Each dict has:
        test_case        (str)       – e.g. "test copilot chat end to end"
        exception_type   (str|None)  – e.g. "AssertionFailedError"
        exception_message(str|None)  – text following the exception class name
    """
    if not log_text:
        return []
    log_text = _TIMESTAMP_RE.sub("", log_text)
    results = []
    matches = list(_FAILED_LINE_RE.finditer(log_text))
    for i, m in enumerate(matches):
        if m.group(1) != test_class:
            continue
        test_case = m.group(2).strip()
        # Block ends at the start of the *next* FAILED line to avoid cross-block
        # contamination.  Fall back to a 5 KB window for the final block.
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else block_start + 5000
        block_text = log_text[block_start:block_end]
        exceptions = _EXCEPTION_LINE_RE.findall(block_text)
        if not exceptions:
            results.append({"test_case": test_case, "exception_type": None, "exception_message": None})
            continue
        # Prefer AssertionFailedError (the root assertion check); otherwise use
        # the last (innermost / most specific) exception seen in the block.
        preferred = next((e for e in exceptions if "AssertionFailed" in e[0]), exceptions[-1])
        results.append({
            "test_case": test_case,
            "exception_type": preferred[0],
            "exception_message": preferred[1].strip(" :\t"),
        })
    return results


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\?(\[[\d;]*[A-Za-z])")


def fetch_annotations(owner: str, repo: str, sha: str, ide_type: str, ide_version: str,
                      test_class: str, token: str) -> list[dict]:
    """Fetch check-run annotations from the 'ui test report' check run for this combo.

    The test framework publishes a separate check run named
    'ui test report ({ide_type}, {ide_version}, {test_class})' which carries
    per-test failure annotations. This is distinct from the job check run,
    which only has a generic exit-code annotation.
    Returns a list of annotation dicts, or [] if the check run is not found.
    """
    target_name = f"ui test report ({ide_type}, {ide_version}, {test_class})"
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/check-runs"
    try:
        check_runs = github_get_all_pages(url, token, params={"per_page": 100})
    except Exception as exc:
        print(f"  Warning: could not list check-runs for {sha[:8]}: {exc}", file=sys.stderr)
        return []
    cr = next((c for c in check_runs if c.get("name") == target_name), None)
    if not cr:
        return []
    ann_url = f"https://api.github.com/repos/{owner}/{repo}/check-runs/{cr['id']}/annotations"
    try:
        return github_get_all_pages(ann_url, token)
    except Exception as exc:
        print(f"  Warning: could not fetch annotations for {target_name}: {exc}", file=sys.stderr)
        return []


def parse_annotations(annotations: list[dict]) -> list[dict]:
    """Convert 'ui test report' check-run annotations into the same shape as
    extract_all_failure_reasons.

    Each failure annotation has:
      title   – "ClassName.test method name()" → used as test_case
      message – error text with ANSI escape codes, first non-empty class name is exception_type
    """
    results = []
    for ann in annotations:
        if ann.get("annotation_level") != "failure":
            continue
        # Strip trailing "()" from title to get the plain test case name
        title = re.sub(r"\(\)$", "", (ann.get("title") or "").strip())
        # Strip class prefix "ClassName." if present
        title = re.sub(r"^\w+\.", "", title)
        message = _ANSI_RE.sub("", ann.get("message") or "")
        # Find first line that looks like an exception class name
        exc_type = None
        exc_msg  = None
        lines = [l.strip() for l in message.splitlines() if l.strip()]
        _skip = re.compile(r"^-{3,}|^\s*at |^Caused by|^Screenshot|^Driver doc")
        exc_lines = [(j, l) for j, l in enumerate(lines)
                     if re.match(r"[\w$][\w$.]*(?:Error|Exception|Failure)\b", l)
                     and not _skip.match(l)]
        if exc_lines:
            # Prefer AssertionFailed* as root cause; otherwise take the first match
            preferred = next((x for x in exc_lines if "AssertionFailed" in x[1]), exc_lines[0])
            j, line = preferred
            m = re.match(r"([\w$][\w$.]*(?:Error|Exception|Failure))[::\s]?(.*)", line)
            exc_type = m.group(1).split(".")[-1]
            candidate = m.group(2).strip(" :\t")
            if not candidate:
                # Look for nearest non-decoration line before this one
                for k in range(j - 1, -1, -1):
                    if not _skip.match(lines[k]) and not re.match(r"[\w$][\w$.]*(?:Error|Exception|Failure)\b", lines[k]):
                        candidate = lines[k]
                        break
            exc_msg = candidate or None
        results.append({
            "test_case":         title,
            "exception_type":    exc_type,
            "exception_message": exc_msg,
        })
    return results


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
    sha_pr_map: dict = {}      # head_sha -> pr_info
    sha_created_at: dict = {}  # head_sha -> most recent created_at (ISO string)

    total_runs = len(runs)
    print(f"Fetching jobs for {total_runs} runs...", file=sys.stderr)

    for i, run in enumerate(runs, 1):
        run_id = run["id"]
        attempt = run.get("run_attempt", 1)
        sha = run.get("head_sha", "")
        conclusion = run.get("conclusion")  # None if in progress
        run_url = run.get("html_url", "")
        created_at = run.get("created_at", "")

        pr_info = resolve_pr_info(run, sha_to_pr)
        if sha not in sha_pr_map:
            sha_pr_map[sha] = pr_info
        # Keep the most recent created_at seen for this SHA (ISO strings sort lexicographically)
        if created_at > sha_created_at.get(sha, ""):
            sha_created_at[sha] = created_at

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
                    "job_id": job.get("id"),
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

    # --- Fetch failure reasons for never_passed jobs (step 3b) ---
    # failure_cases: group_key -> list[dict] | None
    #   None  = log could not be fetched
    #   []    = log fetched but no matching FAILED block found
    #   [...] = one dict per FAILED block: {test_case, exception_type, exception_message}
    # Pass 1 — count never_passed per combo (no API calls).
    # Pass 2 — fetch annotations only for the worst combo (capped) + per-PR entries (capped).
    _MAX_SUMMARY_SAMPLES = 5   # annotation fetches for failure_summary dominant-exception detection
    _MAX_PR_SAMPLES      = 3   # annotation fetches per (pr, test_class) entry for failed_cases

    print("Counting never-passed jobs per combo...", file=sys.stderr)
    failure_cases: dict = {}
    combo_counts: dict = defaultdict(int)   # tk -> never_passed group count
    combo_cases: dict = defaultdict(list)   # tk -> flat list of all failure case dicts
    never_passed_groups: list = []          # [(group_key, failed_entry)] for pass 2
    _in_progress = (None, "in_progress", "queued", "waiting")
    for group_key, entries in groups.items():
        if classified[group_key]["status"] != "never_passed":
            continue
        sha, ide_type, ide_version, test_class = group_key
        tk = (ide_type, ide_version, test_class)
        combo_counts[tk] += 1
        failed_entry = next(
            (e for e in reversed(entries)
             if e.get("conclusion") not in ("success",) + _in_progress and e.get("job_id")),
            None,
        )
        never_passed_groups.append((group_key, failed_entry))

    # Identify worst combo upfront so we can prioritise its jobs in pass 2.
    worst_tk = max(combo_counts, key=lambda k: combo_counts[k]) if combo_counts else None

    print("Fetching failure annotations for never_passed jobs...", file=sys.stderr)
    summary_samples: dict = defaultdict(int)   # tk -> fetches done for summary
    pr_samples: dict = defaultdict(int)        # (sha, tk) -> fetches done for this PR entry
    for group_key, failed_entry in never_passed_groups:
        sha, ide_type, ide_version, test_class = group_key
        tk = (ide_type, ide_version, test_class)
        pr_key = (sha, tk)

        # Decide whether to fetch for summary and/or per-PR failed_cases.
        want_summary = (tk == worst_tk and summary_samples[tk] < _MAX_SUMMARY_SAMPLES)
        want_pr      = (pr_samples[pr_key] < _MAX_PR_SAMPLES)

        if not failed_entry or (not want_summary and not want_pr):
            failure_cases[group_key] = None
            continue

        job_id = failed_entry["job_id"]
        annotations = fetch_annotations(owner, repo, sha, ide_type, ide_version, test_class, token)
        parsed = parse_annotations(annotations)
        if not parsed:
            # Fall back to raw log regex when test-report check run is absent
            log_text = fetch_job_log(owner, repo, job_id, token)
            parsed = extract_all_failure_reasons(log_text, test_class) if log_text is not None else None

        failure_cases[group_key] = parsed
        if want_summary:
            combo_cases[tk].extend(parsed or [])
            summary_samples[tk] += 1
        if want_pr:
            pr_samples[pr_key] += 1

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

    # --- Consolidate per_pr: keep only the latest commit's entry per PR number ---
    # If a PR has multiple commits pushed (each triggering a separate workflow run),
    # only the entry for the most recent commit (by created_at) is kept.
    # Entries with pr_number = None (orphaned/unresolved commits) are kept as-is.
    status_order = {"has_failures": 0, "flaky_but_passing": 1, "all_green": 2, "in_progress": 3}
    pr_number_to_best: dict = {}     # pr_number -> per_pr entry with the latest sha_created_at
    pr_number_to_best_ts: dict = {}  # pr_number -> cached winning created_at timestamp
    orphaned_entries = []

    for entry in per_pr:
        pn = entry["pr_number"]
        if pn is None:
            orphaned_entries.append(entry)
            continue
        entry_ts = sha_created_at.get(entry["head_sha"], "")
        if entry_ts > pr_number_to_best_ts.get(pn, ""):
            pr_number_to_best[pn] = entry
            pr_number_to_best_ts[pn] = entry_ts

    # Rebuild per_pr with one entry per distinct PR number, plus orphaned entries
    per_pr = list(pr_number_to_best.values()) + orphaned_entries
    per_pr.sort(key=lambda p: (status_order.get(p["overall_status"], 9), -(p["pr_number"] or 0)))

    # --- Overall aggregate ---
    total_pf = sum(c["passed_first_attempt"] for c in per_test_class)
    total_par = sum(c["passed_after_retry"] for c in per_test_class)
    total_np = sum(c["never_passed"] for c in per_test_class)
    total_ip = sum(c["in_progress"] for c in per_test_class)
    total_instances = total_pf + total_par + total_np + total_ip
    total_resolved = total_pf + total_par + total_np

    # Aggregate retry distribution: merge all per-test-class histograms
    agg_retry_dist: dict = {}
    for tc in per_test_class:
        for k, v in tc.get("retry_distribution", {}).items():
            agg_retry_dist[k] = agg_retry_dist.get(k, 0) + v
    # Express as percentages of total passed_after_retry (only include if retries occurred)
    agg_retry_dist_pct: dict = {}
    if total_par > 0:
        for k in ("1", "2", "3+"):
            count = agg_retry_dist.get(k, 0)
            if count > 0:
                agg_retry_dist_pct[k] = round(count / total_par * 100, 1)

    aggregate = {
        "total_pr_test_instances": total_instances,
        "passed_first_attempt": total_pf,
        "passed_after_retry": total_par,
        "never_passed": total_np,
        "in_progress": total_ip,
        "total_retry_attempts": total_retry_attempts,
        "retry_distribution": agg_retry_dist,
        "retry_distribution_pct": agg_retry_dist_pct,
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
                    "failed_cases": failure_cases.get(
                        (pr["head_sha"], tr["ide_type"], tr["ide_version"], tr["test_class"])
                    ),
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

    # --- Failure summary: worst (ide_type, ide_version, test_class) combo ---
    # combo_counts and combo_cases were built during the log-fetching pass above.

    failure_summary = None
    if combo_counts:
        worst_tk = max(combo_counts, key=lambda k: combo_counts[k])
        w_ide_type, w_ide_version, w_test_class = worst_tk
        all_cases = combo_cases[worst_tk]
        exc_counts = Counter(c["exception_type"] for c in all_cases if c.get("exception_type"))
        dominant_exc_type = exc_counts.most_common(1)[0][0] if exc_counts else None
        dominant_msg = next(
            (c["exception_message"] for c in all_cases
             if c.get("exception_type") == dominant_exc_type and c.get("exception_message")),
            None,
        )
        failure_summary = {
            "worst_combo": {
                "ide_type": w_ide_type,
                "ide_version": w_ide_version,
                "test_class": w_test_class,
                "never_passed_count": combo_counts[worst_tk],
            },
            "dominant_exception_type": dominant_exc_type,
            "dominant_exception_message": dominant_msg,
            "occurrence_count": exc_counts.get(dominant_exc_type, 0) if exc_counts else 0,
        }

    return {
        "aggregate": aggregate,
        "per_test_class": per_test_class,
        "per_pr": per_pr,
        "top_flaky_tests": top_flaky,
        "prs_with_persistent_failures": prs_with_failures,
        "failure_summary": failure_summary,
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
        "failure_summary": result["failure_summary"],
        "aggregate": result["aggregate"],
        "per_test_class": result["per_test_class"],
        "per_pr": result["per_pr"],
        "top_flaky_tests": result["top_flaky_tests"],
        "prs_with_persistent_failures": result["prs_with_persistent_failures"],
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
