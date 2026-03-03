"""Build a personal Teams notification payload from the ui_test_health.json report."""
import json
import os


def build_message(data: dict) -> str:
    meta    = data["metadata"]
    agg     = data["aggregate"]
    per_tc  = data.get("per_test_case") or []
    worst   = data.get("worst_flaky_test_case")

    since = meta["since"][:10]
    until = meta["until"][:10]
    prs   = meta["total_prs_analyzed"]
    runs  = meta["total_workflow_runs"]

    pass_any   = agg["pass_rate_any_attempt_pct"]
    pass_first = agg["first_attempt_pass_rate_pct"]
    retried    = agg["total_retry_attempts"]
    retry_succ = agg["retry_success_rate_pct"]
    never      = agg["never_passed_rate_pct"]

    lines = [
        f"## 📊 UI Test Health — Last 3 Days ({since} → {until})",
        "",
        f"**PRs analyzed:** {prs} &nbsp;|&nbsp; **Runs:** {runs} &nbsp;|&nbsp; **Pass (any):** {pass_any}% &nbsp;|&nbsp; **First-attempt:** {pass_first}%",
        f"**Re-runs:** {retried} &nbsp;|&nbsp; **Retry success:** {retry_succ}% &nbsp;|&nbsp; **Never-passed:** {never}%",
        "",
    ]

    # Worst flaky test case callout
    if worst:
        score = worst["flakiness_score"]
        run_url = worst.get("latest_run_url", "")
        label = f"{worst['ide_type']} {worst['ide_version']} — {worst['test_class']}.{worst['test_case']}"
        run_link = f" — [latest run]({run_url})" if run_url else ""
        lines += [
            f"⚠️ **Worst:** `{label}` &nbsp;|&nbsp; flakiness: **{score}** &nbsp;|&nbsp; never-passed: **{worst['never_passed']}×**{run_link}",
            "",
        ]

    # Per-test-case table, grouped by (ide_type, ide_version, test_class)
    if per_tc:
        lines += [
            "### 🔬 Per-Test-Case",
            "",
            "| IDE | Version | Test Class | Test Case | First-Pass% | Any-Pass% | Flakiness |",
            "|---|---|---|---|---|---|---|",
        ]
        # Sort: worst flakiness first, then alphabetically
        sorted_tc = sorted(per_tc, key=lambda x: (
            x["ide_type"], x["ide_version"], x["test_class"],
            -x["flakiness_score"], -x["never_passed"], x["test_case"]
        ))
        for tc in sorted_tc:
            score = tc["flakiness_score"]
            emoji = "🟢" if score < 0.15 else ("🟡" if score <= 0.35 else "🔴")
            lines.append(
                f"| {tc['ide_type']} | {tc['ide_version']} | {tc['test_class']}"
                f" | {tc['test_case']}"
                f" | {tc['first_attempt_pass_rate_pct']}%"
                f" | {tc['any_attempt_pass_rate_pct']}%"
                f" | {emoji} {score} |"
            )

    # Root cause analysis from Copilot CLI (injected via env var by workflow)
    root_cause = os.environ.get("ROOT_CAUSE_ANALYSIS", "").strip()
    if root_cause:
        lines += [
            "",
            "### 🤖 Root Cause Analysis",
            "",
            root_cause,
        ]

    # Unstable test cases: show success rate + trimmed failure message
    unstable = [
        tc for tc in per_tc
        if tc["first_attempt_pass_rate_pct"] < 100 and tc["total_instances"] >= 2
    ]
    unstable.sort(key=lambda x: (x["first_attempt_pass_rate_pct"], -x["total_instances"]))
    if unstable:
        lines += ["", "### ⚠️ Unstable Test Cases", ""]
        for tc in unstable[:5]:
            label = f"{tc['ide_type']} {tc['ide_version']} — {tc['test_class']}.{tc['test_case']}"
            run_link = f" · [run]({tc['latest_run_url']})" if tc.get("latest_run_url") else ""
            lines.append(
                f"**{label}**{run_link}  "
                f"Success: **{tc['first_attempt_pass_rate_pct']}%** "
                f"({tc['passed_first_attempt']}/{tc['total_instances']} runs) · "
                f"Any-attempt: {tc['any_attempt_pass_rate_pct']}%"
            )
            msg = tc.get("failure_message", "").strip()
            if msg:
                if len(msg) > 300:
                    msg = msg[:300] + "…"
                lines.append(f"> 💥 `{msg}`")
            lines.append("")

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
        "recipient": "nliu@microsoft.com",
    }

    compact = json.dumps(payload)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as out:
            out.write(f"payload={compact}\n")

    print(f"Payload built — title: {payload['title']}")


if __name__ == "__main__":
    main()
