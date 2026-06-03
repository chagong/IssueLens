#!/usr/bin/env python3
"""Deterministic gate that verifies a generated SLA script before it is trusted.

The workflow generates `sla_check.py` from the target repo's SLA policy on every
run. Because that generation is done by an AI, we must NOT trust the AI's own
"it works" report. Instead this verifier runs the generated script against a
fixed fixture with known-correct expected verdicts, entirely offline, and fails
(exit 1) if the script is broken or its verdicts are wrong.

What it checks:
  1. The script runs without error on the fixture (subprocess, exit 0).
  2. Output is a JSON array of the same length and order as the input.
  3. Every issue gained a valid `sla_status` (GOOD|WARNING|VIOLATION), an
     integer `days_open` >= 0, and a non-empty `sla_details` string.
  4. Every issue's `sla_status` matches the expected verdict.
  5. Original fields (assignees, labels, url, ...) are preserved.

The fixture uses `{{NOW}}` / `{{NOW-<N>d}}` placeholders for timestamps so the
expected verdicts stay stable no matter when the workflow runs. They are
substituted with real ISO-8601 timestamps here before the script sees them.

Usage:
    python verify_generated.py \
        --script ./sla-gen/sla_check.py \
        --fixture fixtures/sample_issues.json \
        --expected fixtures/expected_output.json \
        --workdir ./sla-gen
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ALLOWED_STATUS = {"GOOD", "WARNING", "VIOLATION"}
_TOKEN_RE = re.compile(r"\{\{\s*NOW(?:\s*-\s*(\d+)\s*d)?\s*\}\}")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def substitute_timestamps(text: str, now: datetime) -> str:
    """Replace {{NOW}} / {{NOW-Nd}} placeholders with real ISO timestamps."""

    def repl(match: re.Match) -> str:
        days = match.group(1)
        when = now - timedelta(days=int(days)) if days else now
        return _iso(when)

    return _TOKEN_RE.sub(repl, text)


def fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", required=True, help="Path to the generated sla_check.py")
    parser.add_argument("--fixture", required=True, help="Path to sample_issues.json")
    parser.add_argument("--expected", required=True, help="Path to expected_output.json")
    parser.add_argument("--workdir", default="", help="Directory for temp I/O files")
    args = parser.parse_args()

    if not os.path.isfile(args.script):
        return fail(f"generated script not found: {args.script}")

    now = datetime.now(timezone.utc)

    with open(args.fixture, encoding="utf-8") as fh:
        fixture_raw = fh.read()
    fixture_issues = json.loads(substitute_timestamps(fixture_raw, now))

    with open(args.expected, encoding="utf-8") as fh:
        expected = {
            str(k): v for k, v in json.load(fh).items() if not k.startswith("_")
        }

    workdir = args.workdir or tempfile.mkdtemp(prefix="sla-verify-")
    os.makedirs(workdir, exist_ok=True)
    in_path = os.path.join(workdir, "verify_input.json")
    out_path = os.path.join(workdir, "verify_output.json")
    with open(in_path, "w", encoding="utf-8") as fh:
        json.dump(fixture_issues, fh, indent=2)

    # The fixture supplies has_parent for every issue, so no token/network is
    # needed. Run in a clean-ish env so a stray token can't change verdicts.
    env = dict(os.environ)
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)

    proc = subprocess.run(
        [sys.executable, args.script, "--input", in_path, "--output", out_path],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.returncode != 0:
        print(proc.stderr.rstrip(), file=sys.stderr)
        return fail(f"generated script exited with code {proc.returncode}")

    if not os.path.isfile(out_path):
        return fail("generated script did not write an output file")

    with open(out_path, encoding="utf-8") as fh:
        try:
            scored = json.load(fh)
        except json.JSONDecodeError as exc:
            return fail(f"output is not valid JSON: {exc}")

    if not isinstance(scored, list) or len(scored) != len(fixture_issues):
        return fail(
            f"output length {len(scored) if isinstance(scored, list) else 'N/A'} "
            f"!= input length {len(fixture_issues)}"
        )

    errors: list[str] = []
    for original, result in zip(fixture_issues, scored):
        num = original["issue_number"]

        # Contract checks.
        status = result.get("sla_status")
        if status not in ALLOWED_STATUS:
            errors.append(f"#{num}: invalid sla_status {status!r}")
        if not isinstance(result.get("days_open"), int) or result.get("days_open", -1) < 0:
            errors.append(f"#{num}: days_open must be an int >= 0, got {result.get('days_open')!r}")
        if not isinstance(result.get("sla_details"), str) or not result.get("sla_details", "").strip():
            errors.append(f"#{num}: sla_details must be a non-empty string")

        # Field-preservation checks.
        for key in ("assignees", "labels", "url", "title"):
            if result.get(key) != original.get(key):
                errors.append(f"#{num}: field {key!r} was not preserved")

        # Verdict check.
        want = expected.get(str(num))
        if want and status != want:
            errors.append(f"#{num}: expected sla_status {want}, got {status}")

    if errors:
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return fail(f"{len(errors)} verification problem(s) in the generated script")

    print(f"OK: generated script passed all {len(fixture_issues)} fixture checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
