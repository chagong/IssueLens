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


def _short_type(exc_type: str | None) -> str | None:
    """Return the simple class name from a fully-qualified exception type."""
    if not exc_type:
        return None
    return exc_type.split(".")[-1]


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

    summary = data.get("failure_summary")
    if summary:
        combo    = summary["worst_combo"]
        label    = f"{combo['ide_type']} {combo['ide_version']} — {combo['test_class']}"
        exc_type = _short_type(summary.get("dominant_exception_type")) or "unknown"
        exc_msg  = _ANSI_RE.sub("", summary.get("dominant_exception_message") or "").strip()
        detail   = f"{exc_type} — {exc_msg}" if exc_msg else exc_type

        # Collect latest_run_urls from all prs_with_persistent_failures entries
        # that match the worst combo, deduplicated.
        run_urls = []
        seen = set()
        for pr in data.get("prs_with_persistent_failures", []):
            for ft in pr.get("failed_tests", []):
                if (ft["ide_type"], ft["ide_version"], ft["test_class"]) == (
                    combo["ide_type"], combo["ide_version"], combo["test_class"]
                ):
                    url = ft.get("latest_run_url", "")
                    if url and url not in seen:
                        seen.add(url)
                        run_id = url.rstrip("/").split("/")[-1]
                        run_urls.append(f"[{run_id}]({url})")

        lines += [
            "",
            "### 💥 Failure Summary",
            "",
            f"Worst offender: {label} ({combo['never_passed_count']} never-passed instance(s))",
            f"Dominant failure: {detail} ({summary['occurrence_count']} occurrence(s))",
        ]
        if run_urls:
            lines.append(f"Affected runs: {', '.join(run_urls)}")

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
