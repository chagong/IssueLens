"""Build a personal Teams notification payload from the ui_test_health.json report."""
import json
import os
import re
from collections import defaultdict


def build_failure_summary(data: dict) -> list:
    """Build a data-driven '### 🔍 Failure Summary' section.

    Groups failure_message values from per_test_case[] into categories
    (element-not-found, assertion, timeout, other), deduplicates them,
    and links each pattern to affected test cases and PR counts.
    """
    per_tc = data.get("per_test_case") or []
    prs_with_failures = data.get("prs_with_persistent_failures") or []

    # 1. Collect test cases that have failures AND a non-empty failure message
    failing_tcs = [
        tc for tc in per_tc
        if (tc.get("never_passed", 0) > 0 or tc.get("flakiness_score", 0.0) > 0)
        and tc.get("failure_message", "").strip()
    ]
    if not failing_tcs:
        return []

    # 2. Build test_class -> set of PR numbers with persistent failures
    class_to_pr_nums: dict = defaultdict(set)
    for pr in prs_with_failures:
        pr_num = pr.get("pr_number")
        if pr_num is None:
            continue
        for ft in pr.get("failed_tests", []):
            cls = ft.get("test_class", "")
            if cls:
                class_to_pr_nums[cls].add(pr_num)

    # 3. Categorize (first match wins)
    def categorize(msg: str) -> str:
        lower = msg.lower()
        if any(k in lower for k in (
            "waitforexception", "elementnotfound", "element not found",
            "nosuchelementexception", "unable to find element",
        )):
            return "element_not_found"
        if any(k in lower for k in (
            "assertionerror", "expected:", "but was:", "assertionfailederror",
        )) or lower.startswith("assert"):
            return "assertion"
        if any(k in lower for k in ("timeout", "timed out", "timedout")):
            return "timeout"
        return "other"

    CATEGORY_LABELS = {
        "element_not_found": "🔎 Element Not Found",
        "assertion":         "❌ Assertion Failures",
        "timeout":           "⏱️ Timeouts",
        "other":             "⚙️ Other Failures",
    }
    CATEGORY_ORDER = ["element_not_found", "assertion", "timeout", "other"]

    def normalize_msg(msg: str) -> str:
        msg = msg.strip()
        if len(msg) > 200:
            msg = msg[:200] + "…"
        return re.sub(r"\s+", " ", msg)

    # 4. Group by (category, normalized_message) -> [tc, ...]
    buckets: dict = defaultdict(list)
    for tc in failing_tcs:
        cat = categorize(tc["failure_message"])
        norm = normalize_msg(tc["failure_message"])
        buckets[(cat, norm)].append(tc)

    # 5. Render
    lines = ["", "### 🔍 Failure Summary", ""]
    any_content = False

    for cat in CATEGORY_ORDER:
        cat_groups = [
            (norm, tcs)
            for (c, norm), tcs in buckets.items()
            if c == cat
        ]
        if not cat_groups:
            continue

        cat_groups.sort(key=lambda x: (-len(x[1]), x[0]))
        top_groups = cat_groups[:3]
        total_in_cat = sum(len(tcs) for _, tcs in cat_groups)
        label = CATEGORY_LABELS[cat]
        lines.append(f"**{label} ({total_in_cat} test{'s' if total_in_cat != 1 else ''}):**")

        for norm_msg, tcs in top_groups:
            tc_names = sorted({tc["test_case"] for tc in tcs})
            tc_display = ", ".join(f"`{n}`" for n in tc_names) if len(tc_names) <= 3 else f"{len(tc_names)} tests"
            affected_prs: set = set()
            for tc in tcs:
                affected_prs.update(class_to_pr_nums.get(tc["test_class"], set()))
            pr_suffix = f" — **{len(affected_prs)} PR(s) affected**" if affected_prs else ""
            lines.append(f"- `{norm_msg}` — {tc_display}{pr_suffix}")

        extra = len(cat_groups) - len(top_groups)
        if extra > 0:
            lines.append(f"  _…and {extra} more distinct message(s)_")
        lines.append("")
        any_content = True

    if not any_content:
        return []

    # 6. PRs with persistent failures list (up to 5)
    if prs_with_failures:
        pr_items = []
        for pr in sorted(prs_with_failures, key=lambda p: -(p.get("pr_number") or 0))[:5]:
            num = pr.get("pr_number", "?")
            title = pr.get("pr_title", "")
            url = pr.get("pr_url", "")
            short_title = (title[:60] + "…") if len(title) > 60 else title
            pr_items.append(f"[#{num} {short_title}]({url})" if url else f"#{num} {short_title}")
        lines.append(f"**PRs with persistent failures:** {' · '.join(pr_items)}")
        lines.append("")

    return lines


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

    # Data-driven failure summary
    lines += build_failure_summary(data)

    # Root cause analysis from Copilot CLI (injected via env var by workflow)
    root_cause = os.environ.get("ROOT_CAUSE_ANALYSIS", "").strip()
    if root_cause:
        lines += [
            "",
            "### 🤖 Root Cause (Copilot)",
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
