#!/usr/bin/env python3
"""Render a data-facing HTML report for an SLA-evaluated triage-results.json.

Charts are rendered server-side with matplotlib and embedded as inline base64
PNG <img> tags (email clients strip <script>, so Chart.js/Plotly cannot be
used). The output is an HTML fragment meant to be the body of the weekly
summary email (passed to notify.py via --content-file).

Charts produced:
  * SLA status distribution (donut)
  * SLA status by age bucket (stacked bar)
  * Age distribution of open issues (histogram by day buckets)
  * Open issues by assignee (horizontal bar, top 15)
  * SLA status by assignee (stacked horizontal bar, top 12)
  * Top labels (horizontal bar)
  * SLA status by label (stacked horizontal bar, top 12)
  * SLA violations by label (horizontal bar, top 12)

Usage:
    python render_issue_charts.py --input triage-results.json \
        --output report-content.html --title "Weekly Issue Triage"
"""

import argparse
import base64
import html as html_mod
import io
import json
import sys
from collections import Counter
from datetime import date

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print(
        "matplotlib is required. Install with: pip install matplotlib",
        file=sys.stderr,
    )
    sys.exit(1)


plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "figure.facecolor": "white",
        "axes.facecolor": "#fafafa",
        "axes.grid": True,
        "grid.alpha": 0.3,
    }
)

STATUS_COLORS = {"GOOD": "#43a047", "WARNING": "#fdd835", "VIOLATION": "#ef5350"}


def esc(text) -> str:
    return html_mod.escape(str(text))


def fig_to_base64(fig, dpi=150) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def img_tag(b64: str, alt: str = "chart") -> str:
    return (
        f'<img src="data:image/png;base64,{b64}" alt="{esc(alt)}" '
        'style="max-width:100%;height:auto;display:block;margin:8px auto;">'
    )


# ── charts ────────────────────────────────────────────────────────────────
def chart_sla_donut(counts: dict):
    labels, sizes, colors = [], [], []
    for status in ("GOOD", "WARNING", "VIOLATION"):
        if counts.get(status, 0) > 0:
            labels.append(f"{status} ({counts[status]})")
            sizes.append(counts[status])
            colors.append(STATUS_COLORS[status])
    if not sizes:
        return None
    fig, ax = plt.subplots(figsize=(6, 4))
    wedges, _, autotexts = ax.pie(
        sizes,
        colors=colors,
        autopct="%1.1f%%",
        startangle=140,
        pctdistance=0.78,
        wedgeprops={"width": 0.42, "edgecolor": "white"},
        textprops={"fontsize": 9, "fontweight": "bold"},
    )
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1, 0.5), fontsize=9)
    ax.set_title("SLA Status Distribution")
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_by_assignee(issues: list[dict]):
    counter: Counter = Counter()
    for issue in issues:
        for login in issue.get("assignees", []):
            counter[login] += 1
        if not issue.get("assignees"):
            counter["(unassigned)"] += 1
    if not counter:
        return None
    top = counter.most_common(15)
    names = [n for n, _ in top][::-1]
    vals = [v for _, v in top][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3, len(names) * 0.45)))
    bars = ax.barh(range(len(names)), vals, color="#42a5f5", edgecolor="white", height=0.65)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    for bar, val in zip(bars, vals):
        ax.text(
            bar.get_width() + max(vals) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            ha="left",
            va="center",
            fontsize=9,
            fontweight="bold",
        )
    ax.set_xlabel("Open Issues")
    ax.set_title("Open Issues by Assignee (Top 15)")
    ax.set_xlim(0, max(vals) * 1.15)
    fig.tight_layout()
    return fig_to_base64(fig)


AGE_BUCKETS = [(0, 1, "0-1d"), (2, 3, "2-3d"), (4, 7, "4-7d"),
               (8, 14, "8-14d"), (15, 30, "15-30d"), (31, 10**9, "30d+")]


def _bucket_index(days: int) -> int:
    for i, (lo, hi, _) in enumerate(AGE_BUCKETS):
        if lo <= days <= hi:
            return i
    return len(AGE_BUCKETS) - 1


def chart_age_histogram(issues: list[dict]):
    if not issues:
        return None
    counts = [0] * len(AGE_BUCKETS)
    for issue in issues:
        counts[_bucket_index(issue.get("days_open", 0))] += 1
    labels = [b[2] for b in AGE_BUCKETS]
    fig, ax = plt.subplots(figsize=(8, 3.5))
    colors = ["#66bb6a", "#9ccc65", "#fdd835", "#ffa726", "#ff7043", "#ef5350"]
    bars = ax.bar(labels, counts, color=colors, edgecolor="white", width=0.7)
    for bar, val in zip(bars, counts):
        if val:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(counts) * 0.01,
                str(val),
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
            )
    ax.set_ylabel("Issues")
    ax.set_title("Open Issue Age Distribution")
    ax.set_ylim(0, max(counts) * 1.2 if any(counts) else 1)
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_top_labels(issues: list[dict]):
    counter: Counter = Counter()
    for issue in issues:
        for lbl in issue.get("labels", []):
            counter[lbl] += 1
    if not counter:
        return None
    top = counter.most_common(12)
    names = [n for n, _ in top][::-1]
    vals = [v for _, v in top][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3, len(names) * 0.45)))
    bars = ax.barh(range(len(names)), vals, color="#7e57c2", edgecolor="white", height=0.65)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    for bar, val in zip(bars, vals):
        ax.text(
            bar.get_width() + max(vals) * 0.01,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            ha="left",
            va="center",
            fontsize=9,
            fontweight="bold",
        )
    ax.set_xlabel("Issues")
    ax.set_title("Top Labels")
    ax.set_xlim(0, max(vals) * 1.15)
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_status_by_age(issues: list[dict]):
    if not issues:
        return None
    labels = [b[2] for b in AGE_BUCKETS]
    series = {s: [0] * len(AGE_BUCKETS) for s in ("GOOD", "WARNING", "VIOLATION")}
    for issue in issues:
        status = issue.get("sla_status", "GOOD")
        if status in series:
            series[status][_bucket_index(issue.get("days_open", 0))] += 1
    fig, ax = plt.subplots(figsize=(8, 3.5))
    bottom = [0] * len(AGE_BUCKETS)
    for status in ("GOOD", "WARNING", "VIOLATION"):
        ax.bar(
            labels,
            series[status],
            bottom=bottom,
            color=STATUS_COLORS[status],
            label=status,
            edgecolor="white",
            width=0.7,
        )
        bottom = [a + b for a, b in zip(bottom, series[status])]
    ax.set_ylabel("Issues")
    ax.set_title("SLA Status by Age Bucket")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig_to_base64(fig)


def _stacked_status_barh(title: str, ranking: list[tuple[str, dict]], xlabel: str):
    """Render a horizontal stacked bar of SLA status per category (assignee/label)."""
    if not ranking:
        return None
    names = [n for n, _ in ranking][::-1]
    per = [c for _, c in ranking][::-1]
    totals = [sum(c.values()) for c in per]
    fig, ax = plt.subplots(figsize=(8, max(3, len(names) * 0.5)))
    left = [0] * len(names)
    for status in ("GOOD", "WARNING", "VIOLATION"):
        vals = [c.get(status, 0) for c in per]
        ax.barh(
            range(len(names)),
            vals,
            left=left,
            color=STATUS_COLORS[status],
            label=status,
            edgecolor="white",
            height=0.65,
        )
        left = [a + b for a, b in zip(left, vals)]
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    for i, total in enumerate(totals):
        ax.text(total + max(totals) * 0.01, i, str(total),
                ha="left", va="center", fontsize=9, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    ax.set_xlim(0, max(totals) * 1.15 if totals else 1)
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_status_by_assignee(issues: list[dict], top: int = 12):
    by_assignee: dict[str, Counter] = {}
    for issue in issues:
        status = issue.get("sla_status", "GOOD")
        targets = issue.get("assignees") or ["(unassigned)"]
        for login in targets:
            by_assignee.setdefault(login, Counter())[status] += 1
    if not by_assignee:
        return None
    ranking = sorted(by_assignee.items(), key=lambda kv: sum(kv[1].values()), reverse=True)[:top]
    return _stacked_status_barh(
        f"SLA Status by Assignee (Top {len(ranking)})", ranking, "Open Issues"
    )


def chart_status_by_label(issues: list[dict], top: int = 12):
    by_label: dict[str, Counter] = {}
    for issue in issues:
        status = issue.get("sla_status", "GOOD")
        for lbl in issue.get("labels", []):
            by_label.setdefault(lbl, Counter())[status] += 1
    if not by_label:
        return None
    ranking = sorted(by_label.items(), key=lambda kv: sum(kv[1].values()), reverse=True)[:top]
    return _stacked_status_barh(
        f"SLA Status by Label (Top {len(ranking)})", ranking, "Issues"
    )


def chart_violations_by_label(issues: list[dict], top: int = 12):
    counter: Counter = Counter()
    for issue in issues:
        if issue.get("sla_status") != "VIOLATION":
            continue
        labels = issue.get("labels") or ["(no label)"]
        for lbl in labels:
            counter[lbl] += 1
    if not counter:
        return None
    ranking = counter.most_common(top)
    names = [n for n, _ in ranking][::-1]
    vals = [v for _, v in ranking][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3, len(names) * 0.45)))
    bars = ax.barh(range(len(names)), vals, color=STATUS_COLORS["VIOLATION"],
                   edgecolor="white", height=0.65)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    for bar, val in zip(bars, vals):
        ax.text(bar.get_width() + max(vals) * 0.01, bar.get_y() + bar.get_height() / 2,
                str(val), ha="left", va="center", fontsize=9, fontweight="bold")
    ax.set_xlabel("SLA Violations")
    ax.set_title(f"SLA Violations by Label (Top {len(names)})")
    ax.set_xlim(0, max(vals) * 1.15)
    fig.tight_layout()
    return fig_to_base64(fig)


# ── tables ────────────────────────────────────────────────────────────────
def counts_table(counts: dict) -> str:
    rows = [
        ("Total open issues", counts["total"]),
        ("✅ SLA Good", counts["GOOD"]),
        ("⚠️ SLA Warning", counts["WARNING"]),
        ("❌ SLA Violation", counts["VIOLATION"]),
    ]
    body = "".join(
        f'<tr><td style="border:1px solid #e1e4e8;padding:8px;">{esc(name)}</td>'
        f'<td style="border:1px solid #e1e4e8;padding:8px;">{val}</td></tr>'
        for name, val in rows
    )
    return (
        '<table style="border-collapse:collapse;width:100%;">'
        '<tr style="background:#f6f8fa;">'
        '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Metric</th>'
        '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Count</th></tr>'
        f"{body}</table>"
    )


def violations_table(issues: list[dict]) -> str:
    violations = sorted(
        (i for i in issues if i.get("sla_status") == "VIOLATION"),
        key=lambda x: x.get("days_open", 0),
        reverse=True,
    )[:20]
    if not violations:
        return "<p>No SLA violations. 🎉</p>"
    rows = "".join(
        f'<tr><td style="border:1px solid #e1e4e8;padding:8px;">'
        f'<a href="{esc(i["url"])}" style="color:#0366d6;">#{i["issue_number"]}</a></td>'
        f'<td style="border:1px solid #e1e4e8;padding:8px;">{esc(i["title"])}</td>'
        f'<td style="border:1px solid #e1e4e8;padding:8px;">{i.get("days_open", 0)}</td>'
        f'<td style="border:1px solid #e1e4e8;padding:8px;">{esc(", ".join(i.get("assignees", [])) or "—")}</td></tr>'
        for i in violations
    )
    return (
        '<table style="border-collapse:collapse;width:100%;">'
        '<tr style="background:#f6f8fa;">'
        '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Issue</th>'
        '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Title</th>'
        '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Days Open</th>'
        '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Assignees</th></tr>'
        f"{rows}</table>"
    )


def section(title: str, b64: str | None) -> str:
    if not b64:
        return ""
    return (
        f'<h2 style="color:#24292e;margin-top:24px;">{esc(title)}</h2>'
        f"{img_tag(b64, title)}"
    )


def build_report(issues: list[dict]) -> str:
    counts = {
        "total": len(issues),
        "GOOD": sum(1 for i in issues if i.get("sla_status") == "GOOD"),
        "WARNING": sum(1 for i in issues if i.get("sla_status") == "WARNING"),
        "VIOLATION": sum(1 for i in issues if i.get("sla_status") == "VIOLATION"),
    }
    parts = [
        '<h2 style="color:#24292e;">Overview</h2>',
        counts_table(counts),
        section("SLA Status Distribution", chart_sla_donut(counts)),
        section("SLA Status by Age Bucket", chart_status_by_age(issues)),
        section("Open Issue Age Distribution", chart_age_histogram(issues)),
        section("Open Issues by Assignee", chart_by_assignee(issues)),
        section("SLA Status by Assignee", chart_status_by_assignee(issues)),
        section("Top Labels", chart_top_labels(issues)),
        section("SLA Status by Label", chart_status_by_label(issues)),
        section("SLA Violations by Label", chart_violations_by_label(issues)),
        '<h2 style="color:#24292e;margin-top:24px;">20 Oldest SLA Violations</h2>',
        violations_table(issues),
    ]
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True, help="HTML fragment output path")
    parser.add_argument("--title", default="Weekly Issue Triage")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        issues = json.load(fh)

    content = build_report(issues)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(f"Rendered report for {len(issues)} issues -> {args.output} ({date.today()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
