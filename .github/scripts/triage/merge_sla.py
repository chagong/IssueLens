#!/usr/bin/env python3
"""Merge per-issue SLA verdicts (produced by the Copilot `check-sla` runs) onto
the assignee roster fetched in the prepare stage.

Each Copilot run writes a `sla-<issue_number>.json` file shaped like:
    {
      "issue_number": 123,
      "sla_status": "VIOLATION",   # GOOD | WARNING | VIOLATION
      "days_open": 12,
      "sla_details": "No parent link and past the 7-day grace period."
    }

This script reads the roster (a list of issue dicts), looks up every verdict
file in the verdicts directory, and copies `sla_status`, `days_open` and
`sla_details` onto the matching roster entry. Issues without a usable verdict
default to GOOD so they are never mis-reported as violations.

Usage:
    python merge_sla.py --roster triage-results.json \
        --verdicts-dir sla-verdicts --output triage-results.json
"""

import argparse
import glob
import json
import os
import sys


VALID_STATUSES = {"GOOD", "WARNING", "VIOLATION"}


def load_verdicts(verdicts_dir: str) -> dict[int, dict]:
    verdicts: dict[int, dict] = {}
    if not os.path.isdir(verdicts_dir):
        print(f"Verdicts dir '{verdicts_dir}' not found; treating all issues as GOOD.")
        return verdicts

    for path in sorted(glob.glob(os.path.join(verdicts_dir, "sla-*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  Skipping unreadable verdict {path}: {exc}", file=sys.stderr)
            continue

        number = data.get("issue_number")
        if number is None:
            print(f"  Skipping verdict without issue_number: {path}", file=sys.stderr)
            continue

        status = str(data.get("sla_status", "")).upper()
        if status not in VALID_STATUSES:
            print(f"  Verdict for #{number} has invalid status '{status}'; defaulting to GOOD.")
            status = "GOOD"

        verdicts[int(number)] = {
            "sla_status": status,
            "days_open": int(data.get("days_open") or 0),
            "sla_details": str(data.get("sla_details", "")),
        }
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", required=True, help="Roster JSON from the prepare stage.")
    parser.add_argument("--verdicts-dir", required=True, help="Directory with sla-*.json files.")
    parser.add_argument("--output", required=True, help="Where to write the merged JSON.")
    args = parser.parse_args()

    with open(args.roster, encoding="utf-8") as fh:
        issues = json.load(fh)

    verdicts = load_verdicts(args.verdicts_dir)

    merged = 0
    for issue in issues:
        verdict = verdicts.get(issue.get("issue_number"))
        if verdict:
            issue.update(verdict)
            merged += 1
        else:
            # Safe default — never escalate an un-evaluated issue to a violation.
            issue.setdefault("sla_status", "GOOD")
            issue.setdefault("days_open", 0)
            issue.setdefault("sla_details", "No SLA verdict produced.")

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(issues, fh, indent=2)

    violations = sum(1 for i in issues if i.get("sla_status") == "VIOLATION")
    print(
        f"Merged {merged}/{len(issues)} verdict(s); "
        f"{violations} VIOLATION(s) in the final roster -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
