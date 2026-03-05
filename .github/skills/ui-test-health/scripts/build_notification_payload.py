"""Build a personal Teams notification payload from the ui_test_health.json report."""
import json
import os


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


def build_message(data: dict) -> str:
    meta     = data["metadata"]
    agg      = data["aggregate"]
    per_tc   = data["per_test_class"]
    failures = data["prs_with_persistent_failures"]

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
        f"**PRs analyzed:** {prs} &nbsp;|&nbsp; **Runs:** {runs} &nbsp;|&nbsp; **Pass (any):** {pass_any}% &nbsp;|&nbsp; **First-attempt:** {pass_first}%",
        f"**Re-runs:** {retried} &nbsp;|&nbsp; **Retry success:** {retry_succ}% &nbsp;|&nbsp; **Retry dist:** {retry_dist} &nbsp;|&nbsp; **Never-passed:** {never}%",
        "",
        "### 🔬 Per-Test-Class",
        "",
        "| IDE | Version | Test Class | First-Pass% | Any-Pass% | Flakiness |",
        "|---|---|---|---|---|---|",
    ]

    for tc in per_tc:
        score = tc["flakiness_score"]
        emoji = "🟢" if score < 0.15 else ("🟡" if score <= 0.35 else "🔴")
        lines.append(
            f"| {tc['ide_type']} | {tc['ide_version']} | {tc['test_class']}"
            f" | {tc['first_attempt_pass_rate_pct']}%"
            f" | {tc['any_attempt_pass_rate_pct']}%"
            f" | {emoji} {score} |"
        )

    if failures:
        lines += ["", "### 🚨 PRs with Persistent Failures", ""]
        for pr in failures:
            lines.append(f"**PR #{pr['pr_number']} — {pr['pr_title']}** (@{pr['pr_author']})")
            for entry in pr.get("persistent_failures", []):
                label = f"{entry['ide_type']} {entry['ide_version']} — {entry['test_class']}"
                lines.append(f"  ❌ {label}: failed on all {entry['attempts']} attempt(s)")
                for case in entry.get("failed_cases") or []:
                    exc_type = case.get("exception_type") or "unknown"
                    exc_msg  = case.get("exception_message") or ""
                    detail   = f"{exc_type} — {exc_msg}" if exc_msg else exc_type
                    lines.append(f"    • {case['test_case']}: {detail}")

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
