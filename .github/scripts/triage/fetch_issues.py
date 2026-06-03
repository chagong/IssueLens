#!/usr/bin/env python3
"""Fetch open issues for a repository and normalize them to triage-results.json.

Deterministic — uses only the GitHub REST Search API via stdlib (no AI, no extra deps).

Three query modes keep each workflow's input data as small as possible:

  --mode created    Open issues created on/after --since (weekly full report).
  --mode updated    Open issues updated on/after --since (daily labeling — only
                    the issues that changed in the last 24h, much less data).
  --mode assignees  Open issues assigned to any github-id listed in the IDS env
                    var (per-person SLA notifications).

Usage:
    python fetch_issues.py --repo owner/repo --mode created   --since 2026-01-01 --output triage-results.json
    python fetch_issues.py --repo owner/repo --mode updated   --since 2026-06-01T00:00:00Z --output triage-results.json
    python fetch_issues.py --repo owner/repo --mode assignees --output triage-results.json
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


def _request(url: str, token: str | None) -> dict:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            # Respect secondary rate limits with a simple backoff.
            if exc.code in (403, 429) and attempt < 4:
                time.sleep(2 ** attempt * 5)
                continue
            # Attach the response body so callers can see *why* (e.g. a 422
            # "users cannot be searched" for a non-existent assignee login).
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                body = ""
            if body:
                exc.msg = f"{exc.msg}: {body}"
            raise
    raise RuntimeError("exceeded retry attempts")


def _normalize(item: dict, repo: str) -> dict:
    return {
        "repo": repo,
        "issue_number": item["number"],
        "title": item.get("title", ""),
        "url": item.get("html_url", ""),
        "assignees": [a["login"] for a in item.get("assignees", [])],
        "labels": [lbl["name"] for lbl in item.get("labels", [])],
        "createdAt": item.get("created_at", ""),
        "updatedAt": item.get("updated_at", ""),
    }


def search_issues(repo: str, query: str, token: str | None) -> list[dict]:
    """Run a GitHub issue search and return normalized issue dicts."""
    collected: list[dict] = []
    page = 1
    while True:
        params = urllib.parse.urlencode({"q": query, "per_page": 100, "page": page})
        data = _request(f"{API}/search/issues?{params}", token)
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            # Search API may include PRs; skip anything that is a PR.
            if "pull_request" in item:
                continue
            collected.append(_normalize(item, repo))
        if len(items) < 100:
            break
        page += 1
        if page > 10:  # Search API hard-caps at 1000 results.
            break
    return collected


def fetch_created(repo: str, since: str, token: str | None) -> list[dict]:
    return search_issues(repo, f"repo:{repo} is:issue is:open created:>={since}", token)


def fetch_updated(repo: str, since: str, token: str | None) -> list[dict]:
    return search_issues(repo, f"repo:{repo} is:issue is:open updated:>={since}", token)


def fetch_assignees(repo: str, token: str | None) -> list[dict]:
    """Fetch open issues assigned to any github-id in the IDS env var."""
    raw = os.environ.get("IDS", "").strip()
    if not raw:
        print("IDS env var is empty; no assignees to query.", file=sys.stderr)
        return []
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        print("IDS env var is not valid JSON; cannot query assignees.", file=sys.stderr)
        return []

    logins = [e["github-id"] for e in entries if e.get("github-id")]
    seen: dict[int, dict] = {}
    for login in logins:
        try:
            issues = search_issues(repo, f"repo:{repo} is:issue is:open assignee:{login}", token)
        except urllib.error.HTTPError as exc:
            # GitHub returns 422 when a login can't be searched (e.g. the user
            # no longer exists). That's a per-entry data problem, so skip it and
            # keep going. Auth/rate/other errors are systemic — let them abort.
            if exc.code != 422:
                raise
            print(f"  @{login}: skipped (HTTP 422 — login not searchable)", file=sys.stderr)
            continue
        for issue in issues:
            # Dedupe by issue number (an issue may have multiple assignees).
            seen[issue["issue_number"]] = issue
        print(f"  @{login}: {len(issues)} open assigned issue(s)")
    return list(seen.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--mode",
        choices=["created", "updated", "assignees"],
        default="created",
    )
    parser.add_argument("--since", help="YYYY-MM-DD or ISO timestamp (created/updated modes)")
    parser.add_argument("--output", required=True, help="output JSON path")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if args.mode in ("created", "updated") and not args.since:
        parser.error(f"--since is required for --mode {args.mode}")

    if args.mode == "created":
        issues = fetch_created(args.repo, args.since, token)
        scope = f"created since {args.since}"
    elif args.mode == "updated":
        issues = fetch_updated(args.repo, args.since, token)
        scope = f"updated since {args.since}"
    else:
        issues = fetch_assignees(args.repo, token)
        scope = "assigned to IDS members"

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(issues, fh, indent=2)

    print(f"Fetched {len(issues)} open issues from {args.repo} ({scope})")
    print(f"Saved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
