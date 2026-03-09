"""Build a personal Teams notification payload from the ui_test_health.json report."""
import json
import os
import re


def build_retry_dist_str(rdist: dict) -> str:
    if not rdist:
        return "N/A"
    parts = []
    if "1" in rdist:
        parts.append(f"1 retry: {rdist['1']}%")
    if "2" in rdist:
        parts.append(f"2 retries: {rdist['2']}%")
    if "3+" in rdist:
        parts.append(f"3+ retries: {rdist['3+']}%")
    return ", ".join(parts)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\?(\[[\d;]*[A-Za-z])")


def build_message(data: dict) -> str:
    meta   = data["metadata"]
    agg    = data["aggregate"]
    per_tc = data["per_test_class"]

    since = meta["since"][:10]
    until = meta["until"][:10]
    prs   = meta["total_prs_analyzed"]
    runs  = meta["total_workflow_runs"]

    pass_any   = agg["pass_rate_any_attempt_pct"]
    pass_first = agg["first_attempt_pass_rate_pct"]
    retried    = agg["total_retry_attempts"]
    retry_succ = agg["retry_success_rate_pct"]
    never      = agg["never_passed_rate_pct"]
    retry_dist = build_retry_dist_str(agg.get("retry_distribution_pct", {}))

    lines = [
        f"## 📊 UI Test Health — Last 3 Days ({since} → {until})",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| PRs analyzed | {prs} |",
        f"| Workflow runs | {runs} |",
        f"| Pass rate (any attempt) | {pass_any}% |",
        f"| First-attempt pass rate | {pass_first}% |",
        f"| Never-passed rate | {never}% |",
        f"| Re-runs triggered | {retried} |",
        f"| Retry success rate | {retry_succ}% |",
        f"| Retry distribution | {retry_dist} |",
        "",
        "### 🔬 Per-Test-Class",
        "",
        "| IDE | Version | Test Class | First-Pass% | Any-Pass% |",
        "|---|---|---|---|---|",
    ]

    for tc in per_tc:
        lines.append(
            f"| {tc['ide_type']} | {tc['ide_version']} | {tc['test_class']}"
            f" | {tc['first_attempt_pass_rate_pct']}%"
            f" | {tc['any_attempt_pass_rate_pct']}% |"
        )

    # --- Root Cause Analysis (grouped error types) ---
    rca = data.get("root_cause_analysis")
    error_types = rca.get("error_types", []) if rca else []
    if error_types:
        total = rca.get("total_failure_instances", 0)
        lines += [
            "",
            f"### 🔍 Root Cause Analysis ({total} failure instances)",
            "",
            "| # | Failure Type | Count | % |",
            "|---|---|---|---|",
        ]
        for i, et in enumerate(error_types[:8], 1):
            pct = round(et["count"] / total * 100, 1) if total else 0
            label = et["label"]
            if len(label) > 60:
                label = label[:57] + "..."
            lines.append(f"| {i} | {label} | {et['count']} | {pct}% |")

        # Show detail for top 3 error types
        _MAX_DETAIL_TYPES = 3
        _MAX_RUNS_PER_TYPE = 3
        for i, et in enumerate(error_types[:_MAX_DETAIL_TYPES], 1):
            tc = et["test_case"]
            err_msg = _ANSI_RE.sub("", et.get("error_message") or "").strip()
            if err_msg and len(err_msg) > 150:
                err_msg = err_msg[:147] + "..."
            runs_list = et.get("affected_runs", [])[:_MAX_RUNS_PER_TYPE]

            lines += [
                "",
                f"**Type {i}: {et['label']} ({et['count']} occurrences)**",
                "",
                f"**Test:** `{tc}()`",
            ]
            if err_msg:
                lines.append(f"**Error:** `{err_msg}`")
            if runs_list:
                lines += [
                    "",
                    "| # | Run | Suite |",
                    "|---|-----|-------|",
                ]
                for j, run in enumerate(runs_list, 1):
                    lines.append(
                        f"| {j} | [run_{run['run_id']}]({run['run_url']}) | {run['suite']} |"
                    )

    return "\n".join(lines)


def main() -> None:
    with open("output/ui_test_health.json") as f:
        data = json.load(f)

    meta  = data["metadata"]
    since = meta["since"][:10]
    until = meta["until"][:10]

    run_url = (
        os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/"
        + os.environ.get("GITHUB_REPOSITORY", "") + "/actions/runs/"
        + os.environ.get("GITHUB_RUN_ID", "")
    )

    payload = {
        "title": f"UI Test Health Report — {since} to {until}",
        "message": build_message(data),
        "workflowRunUrl": run_url,
        "recipient": "nliu@microsoft.com"
    }

    compact = json.dumps(payload)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as out:
            out.write(f"payload={compact}\n")

    print(f"Payload built — title: {payload['title']}")


if __name__ == "__main__":
    main()
