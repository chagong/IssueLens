"""Extract the worst flaky test case from ui_test_health.json for root cause analysis."""
import argparse
import json
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract worst flaky test case from health report.")
    parser.add_argument("--input", default="output/ui_test_health.json", help="Input JSON report path")
    parser.add_argument("--output", default="output/worst_test.json", help="Output JSON path")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    worst = data.get("worst_flaky_test_case")

    if not worst:
        print("No flaky test cases found — skipping root cause analysis.", file=sys.stderr)
        # Write empty sentinel so downstream jq calls don't fail
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({}, f)
        # Write has_flaky_tests=false to GITHUB_OUTPUT
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a") as out:
                out.write("has_flaky_tests=false\n")
        sys.exit(0)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(worst, f, indent=2)

    print(f"Worst test case: {worst['ide_type']} {worst['ide_version']} — "
          f"{worst['test_class']}.{worst['test_case']} "
          f"(flakiness: {worst['flakiness_score']}, never_passed: {worst['never_passed']})")

    # Write has_flaky_tests=true to GITHUB_OUTPUT
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as out:
            out.write("has_flaky_tests=true\n")


if __name__ == "__main__":
    main()
