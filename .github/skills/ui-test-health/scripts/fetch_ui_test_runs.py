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
from __future__ import annotations

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
        items = data if isinstance(data, list) else data.get("workflow_runs") or data.get("jobs") or data.get("check_runs") or data.get("workflows") or data.get("pull_requests") or []
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
        test_case         (str)       – e.g. "test copilot chat end to end"
        exception_type    (str|None)  – e.g. "WaitForConditionTimeoutException"
        exception_message (str|None)  – human-readable error description
        error_category    (str)       – classified category
        stack_function    (str|None)  – topmost copilot function in stack trace
    """
    if not log_text:
        return []
    log_text = _TIMESTAMP_RE.sub("", log_text)
    _copilot_stack_re = re.compile(r"com\.github\.copilot[\w.]*\.(\w+)\(")
    results = []
    matches = list(_FAILED_LINE_RE.finditer(log_text))
    for i, m in enumerate(matches):
        if m.group(1) != test_class:
            continue
        test_case = m.group(2).strip()
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else block_start + 5000
        block_text = log_text[block_start:block_end]

        # Look for ----Driver Error---- marker in the block
        driver_error_msg = None
        driver_lines = block_text.splitlines()
        for di, dline in enumerate(driver_lines):
            if "----Driver Error----" in dline:
                for dk in range(di + 1, min(di + 5, len(driver_lines))):
                    candidate = driver_lines[dk].strip()
                    if candidate and not candidate.startswith("---") and not candidate.startswith("at "):
                        driver_error_msg = candidate
                        break
                break

        # Extract stack function
        stack_function = None
        for dline in driver_lines:
            m_stack = _copilot_stack_re.search(dline)
            if m_stack:
                stack_function = m_stack.group(1)
                break

        exceptions = _EXCEPTION_LINE_RE.findall(block_text)
        if not exceptions:
            error_category = classify_error_category(None, driver_error_msg, driver_error_msg)
            results.append({
                "test_case": test_case, "exception_type": None,
                "exception_message": driver_error_msg,
                "error_category": error_category, "stack_function": stack_function,
            })
            continue

        # Prefer specific exception types over generic AssertionFailedError.
        _generic = {"AssertionFailedError", "AssertionError", "AssertionFailure"}
        specific = next((e for e in exceptions if e[0].split(".")[-1] not in _generic
                         and e[0].split(".")[-1] != "DriverWithContextError"), None)
        preferred = specific or next((e for e in exceptions if "AssertionFailed" in e[0]), exceptions[-1])
        exc_type = preferred[0].split(".")[-1]
        exc_msg = driver_error_msg or preferred[1].strip(" :\t")
        error_category = classify_error_category(exc_type, exc_msg, driver_error_msg)
        results.append({
            "test_case": test_case,
            "exception_type": exc_type,
            "exception_message": exc_msg,
            "error_category": error_category,
            "stack_function": stack_function,
        })
    return results


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\?(\[[\d;]*[A-Za-z])")


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

_TIMEOUT_RE = re.compile(r"Exceeded timeout \(PT([^)]+)\)|Timeout\((\d+\w?)\)")
_COMPONENT_RE = re.compile(r"Failed: Find (\w+(?:\[.*?\])?)")
_ASSERTION_EXPECT_RE = re.compile(r"Expected .+? but (?:got|was)|expected: <.*?> but was: <")


def classify_error_category(exc_type: str | None, exc_msg: str | None,
                            raw_error: str | None) -> str:
    """Classify an error into a root cause category.

    Categories:
      - timeout:             Exceeded timeout or Timeout(Xs) for condition functions
      - component_not_found: Failed to find a UI component via xpath (includes component lookup timeouts)
      - assertion_mismatch:  Expected X but got Y (logic / assertion failures)
      - install_state:       Install/Details button state mismatch
      - other:               Unclassified

    Order matters: component_not_found is checked before timeout because
    "Timeout(5s): Failed: Find UiComponent[...]" is a component issue, not a
    general condition timeout.
    """
    msg = raw_error or exc_msg or ""

    # Component not found: "Failed: Find UiComponent[xpath=...]" or "Timeout(Xs): Failed: Find..."
    # Must be checked BEFORE timeout — "Timeout(5s): Failed: Find..." is a component issue.
    if "Failed: Find" in msg:
        return "component_not_found"
    if exc_type and "ComponentLookup" in exc_type:
        return "component_not_found"

    # Timeout: "Exceeded timeout (PT30S)..." or "Timeout(5s):..." without "Failed: Find"
    if _TIMEOUT_RE.search(msg):
        return "timeout"
    if exc_type and "Timeout" in exc_type:
        return "timeout"

    # Install button state mismatch
    if "button text to be 'Install'" in msg or "expected: <Install>" in msg:
        return "install_state"

    # Assertion mismatch: "Expected X but got Y" or "expected: <X> but was: <Y>"
    if _ASSERTION_EXPECT_RE.search(msg):
        return "assertion_mismatch"

    if exc_type and "Assertion" in exc_type:
        return "assertion_mismatch"

    return "other"


_check_runs_cache: dict[str, list[dict] | None] = {}


def fetch_annotations(owner: str, repo: str, sha: str, ide_type: str, ide_version: str,
                      test_class: str, token: str) -> list[dict]:
    """Fetch check-run annotations from the 'ui test report' check run for this combo.

    The test framework publishes a separate check run named
    'ui test report ({ide_type}, {ide_version}, {test_class})' which carries
    per-test failure annotations. This is distinct from the job check run,
    which only has a generic exit-code annotation.
    Returns a list of annotation dicts, or [] if the check run is not found.
    Uses a SHA-based cache to avoid redundant check-runs API calls.
    """
    target_name = f"ui test report ({ide_type}, {ide_version}, {test_class})"

    # Cache check-runs per SHA to avoid redundant API calls
    if sha in _check_runs_cache:
        check_runs = _check_runs_cache[sha]
    else:
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/check-runs"
        t0 = time.time()
        try:
            check_runs = github_get_all_pages(url, token, params={"per_page": 100})
        except Exception as exc:
            print(f"  Warning: could not list check-runs for {sha[:8]}: {exc}", file=sys.stderr)
            check_runs = None
        print(f"    check-runs for {sha[:8]}: {len(check_runs or [])} items, {time.time()-t0:.1f}s",
              file=sys.stderr)
        _check_runs_cache[sha] = check_runs

    if not check_runs:
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

    DriverWithContextError is a wrapper whose message body contains the real inner
    exception type and a human-readable description.  The layout after ANSI stripping is:
        DriverWithContextError: <empty or junk>
        ----Driver Error----
        <human-readable message line(s)>
        InnerExceptionType
            at …stack…
    We use the ----Driver Error---- marker to find the most informative error
    description, then extract the specific inner exception type for classification.
    """
    # Wrapper types that carry no useful message of their own
    _WRAPPER_TYPES = {"DriverWithContextError"}
    # Generic assertion types whose inline message (e.g. "expected: <true> but was: <false>")
    # is less informative than the ----Driver Error---- description line.
    _GENERIC_ASSERTION_TYPES = {"AssertionFailedError", "AssertionError", "AssertionFailure",
                                "AssertionFailedError:", "AssertionError:", "AssertionFailure:"}
    _skip = re.compile(r"^-{3,}|^\s*at |^Caused by:|^Screenshot|^Driver doc")
    _exc_re = re.compile(r"^([\w$][\w$.]*(?:Error|Exception|Failure))\b")
    _DRIVER_ERROR_MARKER = "----Driver Error----"
    _copilot_stack_re = re.compile(r"com\.github\.copilot[\w.]*\.(\w+)\(")

    results = []
    for ann in annotations:
        if ann.get("annotation_level") != "failure":
            continue
        # Strip trailing "()" from title; strip class prefix "ClassName."
        title = re.sub(r"\(\)$", "", (ann.get("title") or "").strip())
        title = re.sub(r"^\w+\.", "", title)

        message = _ANSI_RE.sub("", ann.get("message") or "")
        lines = [l.strip() for l in message.splitlines() if l.strip()]

        # --- Extract the ----Driver Error---- message (most informative line) ---
        driver_error_msg = None
        driver_error_idx = None
        for idx, line in enumerate(lines):
            if _DRIVER_ERROR_MARKER in line:
                driver_error_idx = idx
                # The first non-noise, non-exception line after the marker is the
                # human-readable error description.
                for k in range(idx + 1, len(lines)):
                    candidate = lines[k]
                    if _skip.match(candidate) or _exc_re.match(candidate):
                        break
                    driver_error_msg = candidate
                    break
                break

        # --- Extract topmost com.github.copilot function from stack trace ---
        stack_function = None
        search_start = driver_error_idx + 1 if driver_error_idx is not None else 0
        for line in lines[search_start:]:
            m_stack = _copilot_stack_re.search(line)
            if m_stack:
                stack_function = m_stack.group(1)
                break

        # --- Collect all candidate exception lines (not stack / noise) ---
        exc_lines = [
            (j, l) for j, l in enumerate(lines)
            if _exc_re.match(l) and not _skip.match(l)
        ]

        exc_type = exc_msg = None
        if exc_lines:
            def _simple_type(line: str) -> str:
                return line.split(":")[0].strip().split(".")[-1]

            # Prefer specific inner exception types (e.g. WaitForConditionTimeoutException,
            # ComponentLookupException) over generic wrappers and assertion types, because
            # the specific type reveals the actual root cause.
            preferred = (
                next((x for x in exc_lines
                      if _simple_type(x[1]) not in _WRAPPER_TYPES
                      and _simple_type(x[1]) not in _GENERIC_ASSERTION_TYPES), None)
                or next((x for x in exc_lines if "AssertionFailed" in x[1]), None)
                or next((x for x in exc_lines if _simple_type(x[1]) not in _WRAPPER_TYPES), None)
                or exc_lines[0]
            )
            j, line = preferred
            m = _exc_re.match(line)
            exc_type = m.group(1).split(".")[-1]

            # Always prefer the ----Driver Error---- message when available — it
            # contains the actionable human-readable description (e.g. "Exceeded
            # timeout (PT30S)…", "Failed: Find UiComponent[…]", "Expected conflict
            # hint…").  The inline message of generic assertion types like
            # "expected: <true> but was: <false>" is not useful for root cause analysis.
            if driver_error_msg:
                exc_msg = driver_error_msg
            else:
                # Fallback: inline message or backward search
                inline = re.sub(r"^[\w$][\w$.]*(?:Error|Exception|Failure)[:\s]*", "", line).strip(" :\t")
                if inline:
                    exc_msg = inline
                else:
                    for k in range(j - 1, -1, -1):
                        candidate = lines[k]
                        if _skip.match(candidate) or _exc_re.match(candidate):
                            continue
                        if len(candidate.split()) < 2 and candidate.lower() in {"none", "null", "true", "false", ""}:
                            continue
                        exc_msg = candidate
                        break

        # --- Classify error category ---
        error_category = classify_error_category(exc_type, exc_msg, driver_error_msg)

        results.append({
            "test_case":         title,
            "exception_type":    exc_type,
            "exception_message": exc_msg,
            "error_category":    error_category,
            "stack_function":    stack_function,
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


def build_sha_to_pr_from_runs(runs: list) -> dict:
    """Build a sha -> PR info mapping directly from workflow run data.

    Each workflow run contains a pull_requests field with basic PR info.
    This avoids the expensive bulk PR list fetch entirely.
    """
    sha_to_pr: dict = {}
    for run in runs:
        sha = run.get("head_sha", "")
        if not sha or sha in sha_to_pr:
            continue
        prs = run.get("pull_requests") or []
        if prs:
            pr = prs[0]
            fallback_url = pr.get("url", "").replace("api.github.com/repos", "github.com").replace("/pulls/", "/pull/")
            sha_to_pr[sha] = {
                "pr_number": pr.get("number"),
                "pr_title": "",  # title not in run data; enriched later
                "pr_url": fallback_url,
                "pr_author": "",  # author not in run data; enriched later
            }
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


_CATEGORY_DISPLAY = {
    "timeout": "Exceeded Timeout",
    "component_not_found": "UI Component Not Found",
    "assertion_mismatch": "Assertion Mismatch",
    "install_state": "Install Button State",
    "other": "Other",
}


def _extract_timeout_detail(msg: str) -> str:
    """Extract a human-readable timeout sub-label from the error message."""
    m = _TIMEOUT_RE.search(msg or "")
    timeout_val = (m.group(1) or m.group(2)) if m else None
    return f"({timeout_val})" if timeout_val else ""


def _extract_component_detail(msg: str) -> str:
    """Extract a short component identifier from a 'Failed: Find' message."""
    if not msg:
        return "unknown"
    m = re.search(r"Find (\w+)\[", msg)
    component_type = m.group(1) if m else "unknown"
    # Try to extract a recognizable attribute for display
    attr_m = re.search(r"@(?:text|myicon|class|tooltiptext|name)='([^']+)'", msg)
    attr = attr_m.group(1) if attr_m else ""
    if attr:
        return f"{component_type}[{attr}]"
    return component_type


def _build_root_cause_analysis(all_cases: list[dict]) -> dict:
    """Build root cause analysis from all collected failure cases.

    Groups failures by error_category, then builds subcategories within each:
    - timeout: grouped by stack_function
    - component_not_found: grouped by component identifier
    - assertion_mismatch: grouped by assertion description
    - other: grouped by exception_type
    """
    if not all_cases:
        return {"total_failure_instances": 0, "categories": []}

    # Group by category
    by_category: dict = defaultdict(list)
    for case in all_cases:
        cat = case.get("error_category", "other")
        by_category[cat].append(case)

    categories = []
    for cat in ["timeout", "component_not_found", "assertion_mismatch", "install_state", "other"]:
        cases = by_category.get(cat, [])
        if not cases:
            continue

        # Build subcategories based on category type
        sub_groups: dict = defaultdict(list)
        for c in cases:
            msg = c.get("exception_message") or ""
            if cat == "timeout":
                fn = c.get("stack_function")
                detail = _extract_timeout_detail(msg)
                if fn:
                    label = f"{fn} {detail}".strip()
                else:
                    # No copilot stack frame — use the message itself as label
                    label = msg[:80].strip() if msg else "unknown timeout"
            elif cat == "component_not_found":
                label = _extract_component_detail(msg)
            elif cat == "assertion_mismatch":
                # Group by the first ~60 chars of the message to cluster similar assertions
                label = msg[:60].strip() if msg else "unknown"
            elif cat == "install_state":
                label = msg[:60].strip() if msg else "unknown"
            else:
                label = c.get("exception_type") or "unknown"
            sub_groups[label].append(c)

        subcategories = sorted(
            [
                {
                    "label": label,
                    "count": len(sub_cases),
                    "sample_message": next(
                        (c["exception_message"] for c in sub_cases if c.get("exception_message")),
                        None,
                    ),
                }
                for label, sub_cases in sub_groups.items()
            ],
            key=lambda x: -x["count"],
        )

        sample_errors = list({
            c["exception_message"] for c in cases
            if c.get("exception_message")
        })[:5]

        categories.append({
            "category": cat,
            "display_name": _CATEGORY_DISPLAY.get(cat, cat),
            "count": len(cases),
            "pct": round(len(cases) / len(all_cases) * 100, 1),
            "subcategories": subcategories,
            "sample_errors": sample_errors,
        })

    # Sort by count descending
    categories.sort(key=lambda x: -x["count"])

    return {
        "total_failure_instances": len(all_cases),
        "categories": categories,
    }


def _humanize_test_case(test_case: str) -> str:
    """Convert a test method name like 'test terminal feature' to 'Terminal Feature'."""
    name = re.sub(r"^test\s+", "", test_case, flags=re.IGNORECASE).strip()
    return name.title() if name else test_case


def _generate_type_label(test_case: str, category: str, detail_key: str) -> str:
    """Generate a human-readable error-type label.

    Examples:
      - "Copilot Tab Not Found in Terminal Feature"
      - "Condition Timeout in Chat End to End"
      - "Assertion Mismatch in Copilot Chat End to End"
    """
    human_test = _humanize_test_case(test_case)
    if category == "component_not_found":
        # detail_key looks like "UiComponent[ContentTabLabel]" or "ActionButtonUi[Send]"
        # Extract the short attribute for a friendlier label
        m = re.search(r"\[([^\]]+)\]", detail_key)
        attr = m.group(1) if m else detail_key
        return f"{attr} Not Found in {human_test}"
    elif category == "timeout":
        if detail_key and detail_key != "condition function":
            return f"{detail_key} Timeout in {human_test}"
        return f"Condition Timeout in {human_test}"
    elif category == "assertion_mismatch":
        return f"Assertion Mismatch in {human_test}"
    elif category == "install_state":
        return f"Install Button State in {human_test}"
    return f"Error in {human_test}"


def _build_error_type_groups(all_cases: list[dict]) -> list[dict]:
    """Group failure cases into distinct error types for concise reporting.

    Groups by (test_case, error_category, normalized_key) and generates a
    human-readable label for each group. Each group includes deduplicated
    affected runs with suite info.

    Returns a list sorted by count descending, each dict:
        label          – human-readable type label
        count          – number of failure instances
        test_case      – original test method name
        error_message  – representative full error message
        error_category – classified category
        affected_runs  – [{run_id, run_url, suite}] deduplicated
    """
    if not all_cases:
        return []

    groups: dict = defaultdict(list)
    for case in all_cases:
        tc = case.get("test_case") or "unknown"
        cat = case.get("error_category", "other")
        msg = case.get("exception_message") or ""

        if cat == "component_not_found":
            nkey = _extract_component_detail(msg)
        elif cat == "timeout":
            fn = case.get("stack_function")
            nkey = fn if fn else "condition function"
        elif cat == "assertion_mismatch":
            nkey = msg[:80].strip() if msg else "unknown"
        elif cat == "install_state":
            nkey = "install_state"
        else:
            nkey = case.get("exception_type") or "unknown"

        groups[(tc, cat, nkey)].append(case)

    result = []
    for (tc, cat, nkey), cases in groups.items():
        label = _generate_type_label(tc, cat, nkey)

        # Pick the longest non-empty message as representative
        messages = [c.get("exception_message") or "" for c in cases]
        rep_msg = max(messages, key=len) if messages else ""
        # Truncate very long messages for display
        if len(rep_msg) > 200:
            rep_msg = rep_msg[:197] + "..."

        # Deduplicate affected runs by (run_url, suite)
        seen_runs: set = set()
        affected_runs = []
        for c in cases:
            url = c.get("_run_url", "")
            suite = f"{c.get('_ide_type', '')}_{c.get('_ide_version', '')}"
            if not url or (url, suite) in seen_runs:
                continue
            seen_runs.add((url, suite))
            run_id = url.rstrip("/").split("/")[-1]
            affected_runs.append({"run_id": run_id, "run_url": url, "suite": suite})

        result.append({
            "label": label,
            "count": len(cases),
            "test_case": tc,
            "error_message": rep_msg,
            "error_category": cat,
            "affected_runs": affected_runs,
        })

    result.sort(key=lambda x: -x["count"])
    return result[:3]


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

    # --- Fetch failure reasons for all failed jobs (step 3b) ---
    # failure_cases: group_key -> list[dict] | None
    #   None  = log could not be fetched
    #   []    = log fetched but no matching FAILED block found
    #   [...] = one dict per FAILED block: {test_case, exception_type, exception_message, error_category, stack_function}
    # Fetch annotations for never_passed jobs (all), plus a sample of first-attempt
    # failures from passed_after_retry jobs for root cause analysis coverage.
    # never_passed groups are always fully fetched (no cap) — the SHA-level check-runs
    # cache means the real cost is one API call per unique SHA, not per group.
    # passed_after_retry sampling is capped to avoid unnecessary extra calls.
    _MAX_RETRY_ANNOTATION_FETCHES = 20  # cap only for passed_after_retry samples
    _MAX_PR_SAMPLES = 3           # per (sha, test_class) for per-PR failed_cases

    print("Collecting failed jobs for root cause analysis...", file=sys.stderr)
    failure_cases: dict = {}
    all_failure_cases: list = []   # flat list of all failure case dicts for root cause analysis
    combo_counts: dict = defaultdict(int)   # tk -> never_passed group count
    combo_cases: dict = defaultdict(list)   # tk -> flat list of all failure case dicts
    _in_progress = (None, "in_progress", "queued", "waiting")

    # Collect all groups that have failures (never_passed or failed first attempts)
    failed_groups: list = []  # [(group_key, failed_entry, is_never_passed)]
    for group_key, entries in groups.items():
        status = classified[group_key]["status"]
        sha, ide_type, ide_version, test_class = group_key
        tk = (ide_type, ide_version, test_class)

        if status == "never_passed":
            combo_counts[tk] += 1
            failed_entry = next(
                (e for e in reversed(entries)
                 if e.get("conclusion") not in ("success",) + _in_progress and e.get("job_id")),
                None,
            )
            failed_groups.append((group_key, failed_entry, True))
        elif status == "passed_after_retry":
            # The first attempt failed — sample it for root cause analysis
            first = entries[0] if entries else None
            if first and first.get("conclusion") != "success" and first.get("job_id"):
                failed_groups.append((group_key, first, False))

    # Prioritize: never_passed first, then passed_after_retry
    failed_groups.sort(key=lambda x: (0 if x[2] else 1))

    never_passed_groups = [g for g in failed_groups if g[2]]
    retry_groups = [g for g in failed_groups if not g[2]]
    capped_retry_groups = retry_groups[:_MAX_RETRY_ANNOTATION_FETCHES]
    groups_to_fetch = never_passed_groups + capped_retry_groups
    print(f"Fetching failure annotations for {len(groups_to_fetch)} "
          f"of {len(failed_groups)} failed groups "
          f"({len(never_passed_groups)} never-passed + {len(capped_retry_groups)} retry samples)...",
          file=sys.stderr)
    fetch_count = 0
    annotation_miss_count = 0
    pr_samples: dict = defaultdict(int)
    for group_key, failed_entry, is_never_passed in groups_to_fetch:
        sha, ide_type, ide_version, test_class = group_key
        tk = (ide_type, ide_version, test_class)
        pr_key = (sha, tk)

        if not failed_entry:
            if is_never_passed:
                failure_cases[group_key] = None
            continue

        # For per-PR display, cap samples per (sha, test_class)
        want_pr = is_never_passed and pr_samples[pr_key] < _MAX_PR_SAMPLES

        job_id = failed_entry["job_id"]
        fetch_count += 1
        cache_status = "cached" if sha in _check_runs_cache else "new"
        print(f"  [{fetch_count}/{len(groups_to_fetch)}] "
              f"{ide_type}/{ide_version}/{test_class} sha={sha[:8]} ({cache_status})",
              file=sys.stderr)
        annotations = fetch_annotations(owner, repo, sha, ide_type, ide_version, test_class, token)
        parsed = parse_annotations(annotations)
        if not parsed:
            annotation_miss_count += 1
            parsed = None

        if is_never_passed:
            failure_cases[group_key] = parsed
        if parsed:
            # Stamp each case with run metadata for error-type grouping
            run_url = failed_entry.get("run_url", "")
            for case in parsed:
                case["_run_url"] = run_url
                case["_ide_type"] = ide_type
                case["_ide_version"] = ide_version
            all_failure_cases.extend(parsed)
            combo_cases[tk].extend(parsed)
        if want_pr:
            pr_samples[pr_key] += 1

    miss_rate = (annotation_miss_count / fetch_count * 100) if fetch_count else 0
    print(f"Annotation fetch complete: {fetch_count} fetched, {annotation_miss_count} missed "
          f"({miss_rate:.0f}% miss rate), {len(_check_runs_cache)} unique SHAs cached",
          file=sys.stderr)

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
        msg_counts = Counter(
            c["exception_message"] for c in all_cases
            if c.get("exception_type") == dominant_exc_type and c.get("exception_message")
        )
        dominant_msg = msg_counts.most_common(1)[0][0] if msg_counts else None
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

    # --- Root cause analysis: group all failures by error category ---
    root_cause_analysis = _build_root_cause_analysis(all_failure_cases)
    root_cause_analysis["error_types"] = _build_error_type_groups(all_failure_cases)

    return {
        "aggregate": aggregate,
        "per_test_class": per_test_class,
        "per_pr": per_pr,
        "top_flaky_tests": top_flaky,
        "prs_with_persistent_failures": prs_with_failures,
        "failure_summary": failure_summary,
        "root_cause_analysis": root_cause_analysis,
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

    # Step 3+4: Build PR cross-reference from run data, then jobs per run (inside aggregate)
    sha_to_pr = build_sha_to_pr_from_runs(runs)
    print(f"Extracted {len(sha_to_pr)} PR SHAs from workflow runs", file=sys.stderr)

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
        "root_cause_analysis": result["root_cause_analysis"],
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
