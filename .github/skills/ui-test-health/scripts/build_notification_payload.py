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
        # Suppress message if it's only punctuation / single characters (e.g. bare "?")
        if exc_msg and not re.search(r"[A-Za-z0-9]{2,}", exc_msg):
            exc_msg = ""
        # Truncate long messages
        if exc_msg and len(exc_msg) > 120:
            exc_msg = exc_msg[:117] + "..."
        detail   = f"{exc_type} — {exc_msg}" if exc_msg else exc_type

        # Collect latest_run_urls only from entries where the dominant exception was seen.
        _MAX_RUNS = 5
        run_urls = []
        seen = set()
        for pr in data.get("prs_with_persistent_failures", []):
            for ft in pr.get("failed_tests", []):
                if (ft["ide_type"], ft["ide_version"], ft["test_class"]) != (
                    combo["ide_type"], combo["ide_version"], combo["test_class"]
                ):
                    continue
                # Only include if at least one failed_case matches the dominant exception type
                dominant_raw = summary.get("dominant_exception_type") or ""
                matched = any(
                    (c.get("exception_type") or "").endswith(exc_type)
                    or (c.get("exception_type") or "") == dominant_raw
                    for c in (ft.get("failed_cases") or [])
                )
                if not matched:
                    continue
                url = ft.get("latest_run_url", "")
                if url and url not in seen and len(run_urls) < _MAX_RUNS:
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

    # --- Root Cause Analysis ---
    rca = data.get("root_cause_analysis")
    if rca and rca.get("categories"):
        total = rca.get("total_failure_instances", 0)
        lines += [
            "",
            f"### 🔍 Root Cause Analysis ({total} failure instances)",
            "",
            "| Category | Count | % | Top Sub-cause |",
            "|---|---|---|---|",
        ]
        for cat in rca["categories"]:
            top_sub = cat["subcategories"][0]["label"] if cat.get("subcategories") else "-"
            # Truncate long sub-cause labels
            if len(top_sub) > 50:
                top_sub = top_sub[:47] + "..."
            lines.append(
                f"| {cat['display_name']} | {cat['count']} | {cat['pct']}% | {top_sub} |"
            )

        # Show subcategory breakdown for each non-trivial category
        for cat in rca["categories"]:
            subs = cat.get("subcategories", [])
            if len(subs) <= 1:
                continue
            lines += ["", f"**{cat['display_name']}** breakdown:"]
            for sub in subs[:8]:  # cap at 8 subcategories
                label = sub["label"]
                if len(label) > 70:
                    label = label[:67] + "..."
                lines.append(f"- {label}: {sub['count']}x")

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
    }

    compact = json.dumps(payload)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as out:
            out.write(f"payload={compact}\n")

    print(f"Payload built — title: {payload['title']}")


if __name__ == "__main__":
    main()
