#!/usr/bin/env python3
"""EXAMPLE / TEMPLATE SLA evaluation script.

This file is a *reference template* shown to Copilot CLI when it generates the
real, policy-specific `sla_check.py` at workflow run time. It is NOT used
directly by any workflow.

It demonstrates the required structure and the I/O contract described in
../references/IO_CONTRACT.md:

  * the exact command-line interface (--input / --output),
  * reading the issue array and writing it back with sla_status / days_open /
    sla_details added,
  * the `has_parent` shortcut that keeps fixture verification offline,
  * case-insensitive label-group matching,
  * graceful degradation on per-issue API errors.

The POLICY implemented below is only an illustrative default. When generating
the real script, replace the policy logic in `evaluate()` with exactly what the
target repository's .github/sla.md specifies, while keeping the interface and
the input/output shapes identical.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"

# --- Policy constants (REPLACE per the target repo's .github/sla.md) --------- #
TOLERANCE_DAYS = 7
EXEMPT_LABEL_GROUPS = [
    {"need more info", "needs more info", "need-more-info", "needs-more-info"},
    {"need log", "needs log", "need-log", "needs-log"},
]
ATTENTION_LABEL_GROUP = {
    "need attention", "needs attention", "need-attention", "needs-attention"
}


def normalize_label(label: str) -> str:
    """Lower-case and collapse '-' / spaces so variations compare equal."""
    return label.strip().lower().replace("-", " ")


def label_in_group(labels: set[str], group: set[str]) -> bool:
    norm_labels = {normalize_label(lbl) for lbl in labels}
    norm_group = {normalize_label(g) for g in group}
    return bool(norm_labels & norm_group)


def days_open(created_at: str) -> int:
    if not created_at:
        return 0
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - created).days


def fetch_has_parent(repo: str, issue_number: int, token: str | None) -> bool:
    """Return True if the issue has a parent via GitHub's sub-issues API."""
    url = f"{API}/repos/{repo}/issues/{issue_number}/parent"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        # Conservatively treat transient errors as "no parent" without crashing.
        return False
    except Exception:  # noqa: BLE001
        return False


def has_parent(issue: dict, token: str | None) -> bool:
    # Offline shortcut used by the fixture: trust an explicit boolean if present.
    if isinstance(issue.get("has_parent"), bool):
        return issue["has_parent"]
    return fetch_has_parent(issue["repo"], issue["issue_number"], token)


def evaluate(issue: dict, token: str | None) -> None:
    """Apply the SLA policy and set sla_status / days_open / sla_details."""
    labels = set(issue.get("labels", []))
    opened = days_open(issue.get("createdAt", ""))
    issue["days_open"] = opened

    # 1. Exempt labels -> always GOOD.
    if any(label_in_group(labels, grp) for grp in EXEMPT_LABEL_GROUPS):
        issue["sla_status"] = "GOOD"
        issue["sla_details"] = "Exempt: waiting on reporter (need more info / need log)."
        return

    # 2. Within the tolerance window -> GOOD (grace period).
    if opened <= TOLERANCE_DAYS:
        issue["sla_status"] = "GOOD"
        issue["sla_details"] = f"Within {TOLERANCE_DAYS}-day tolerance window (open {opened}d)."
        return

    # 3. Past tolerance: GOOD only if parent link exists AND no attention label.
    parent = has_parent(issue, token)
    attention = label_in_group(labels, ATTENTION_LABEL_GROUP)
    if parent and not attention:
        issue["sla_status"] = "GOOD"
        issue["sla_details"] = "Has parent link and no 'need attention' label."
        return

    reasons = []
    if not parent:
        reasons.append("no parent link")
    if attention:
        reasons.append("has 'need attention' label")
    issue["sla_status"] = "VIOLATION"
    issue["sla_details"] = f"Open {opened}d > {TOLERANCE_DAYS}d and " + "; ".join(reasons) + "."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    with open(args.input, encoding="utf-8") as fh:
        issues = json.load(fh)

    counts = {"GOOD": 0, "WARNING": 0, "VIOLATION": 0}
    for issue in issues:
        evaluate(issue, token)
        counts[issue["sla_status"]] = counts.get(issue["sla_status"], 0) + 1

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(issues, fh, indent=2)

    print(
        f"SLA evaluated for {len(issues)} issues: "
        f"{counts['GOOD']} GOOD, {counts['WARNING']} WARNING, {counts['VIOLATION']} VIOLATION"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
