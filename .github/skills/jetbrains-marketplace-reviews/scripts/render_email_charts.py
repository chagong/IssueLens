#!/usr/bin/env python3
"""
Render JetBrains Marketplace review charts as base64-encoded PNG images
and output an HTML fragment suitable for embedding in email bodies.

Email clients strip <script> tags, so JavaScript-based charting libraries
(Chart.js, Plotly, etc.) cannot be used. This script uses matplotlib to
render charts server-side and embeds them as inline base64 data URIs:

    <img src="data:image/png;base64,..." />

Usage:
    py render_email_charts.py --input reviews.json --output report.html \
       [--title "Plugin Name"] [--json-output charts.json]
"""

import json
import io
import base64
import argparse
import html as html_mod
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
except ImportError:
    print("matplotlib and numpy are required. "
          "Install with: pip install matplotlib numpy")
    exit(1)


# ── helpers ──────────────────────────────────────────────────────────────

def fig_to_base64(fig, dpi=150):
    """Render a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def img_tag(b64, alt="chart"):
    """Return an HTML <img> tag with inline base64 PNG data."""
    return (f'<img src="data:image/png;base64,{b64}" alt="{alt}" '
            f'style="max-width:100%;height:auto;display:block;'
            f'margin:8px auto;">')


def load_reviews(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ── chart functions ──────────────────────────────────────────────────────

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "figure.facecolor": "white",
    "axes.facecolor": "#fafafa",
    "axes.grid": True,
    "grid.alpha": 0.3,
})


def chart_rating_distribution(reviews):
    """Bar chart of overall rating distribution."""
    ratings = Counter(r["rating"] for r in reviews)
    total = len(reviews)
    fig, ax = plt.subplots(figsize=(7, 3.5))
    labels = ["No Rating", "1 Star", "2 Stars", "3 Stars", "4 Stars",
              "5 Stars"]
    values = [ratings.get(i, 0) for i in range(6)]
    colors = ["#bdbdbd", "#ef5350", "#ff9800", "#fdd835", "#66bb6a",
              "#43a047"]
    bars = ax.bar(labels, values, color=colors, edgecolor="white",
                  linewidth=0.5, width=0.65)
    for bar, val in zip(bars, values):
        pct = val / total * 100
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.01,
                f"{val}\n({pct:.1f}%)", ha="center", va="bottom",
                fontsize=9, fontweight="bold")
    ax.set_ylabel("Count")
    ax.set_title("Rating Distribution")
    ax.set_ylim(0, max(values) * 1.2)
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_yearly_avg(reviews):
    """Bar chart of average rating by year."""
    yearly = defaultdict(lambda: {"total": 0, "rated": 0, "sum": 0})
    for r in reviews:
        y = r["date"][:4]
        yearly[y]["total"] += 1
        if r["rating"] > 0:
            yearly[y]["rated"] += 1
            yearly[y]["sum"] += r["rating"]
    years = sorted(yearly.keys())
    if not years:
        return None

    fig, ax = plt.subplots(figsize=(7, 3.5))
    avgs = [yearly[y]["sum"] / yearly[y]["rated"]
            if yearly[y]["rated"] > 0 else 0 for y in years]
    counts = [yearly[y]["rated"] for y in years]
    colors = ["#66bb6a" if a >= 3.5 else "#fdd835" if a >= 2.5
              else "#ff9800" if a >= 2 else "#ef5350" for a in avgs]
    bars = ax.bar(years, avgs, color=colors, edgecolor="white", width=0.55)
    for bar, avg_v, n in zip(bars, avgs, counts):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.08,
                f"{avg_v:.2f}\n(n={n})", ha="center", va="bottom",
                fontsize=9, fontweight="bold")
    ax.axhline(y=3.0, color="#999", linestyle="--", linewidth=1,
               label="Neutral (3.0)")
    ax.set_ylabel("Average Rating")
    ax.set_title("Average Rating by Year")
    ax.set_ylim(0, 5.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_monthly_volume(reviews, months, monthly):
    """Bar chart of monthly review volume."""
    fig, ax = plt.subplots(figsize=(10, 3))
    x = range(len(months))
    vals = [monthly[m]["total"] for m in months]
    ax.bar(x, vals, color="#64b5f6", edgecolor="#42a5f5", linewidth=0.3,
           width=0.8)
    ax.set_xticks(range(0, len(months), 6))
    ax.set_xticklabels([months[i] for i in range(0, len(months), 6)],
                       rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Reviews")
    ax.set_title("Monthly Review Volume")
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_monthly_rating_trend(months, monthly):
    """Line chart: monthly avg + 5-bucket moving avg + neutral line."""
    monthly_avgs = []
    for m in months:
        if monthly[m]["rated"] > 0:
            monthly_avgs.append(monthly[m]["sum"] / monthly[m]["rated"])
        else:
            monthly_avgs.append(None)

    # 5-bucket moving average
    def moving_avg(vals, window=5):
        result = []
        for i in range(len(vals)):
            bucket = [v for v in vals[max(0, i - window // 2):
                                      i + window // 2 + 1]
                      if v is not None]
            result.append(sum(bucket) / len(bucket) if bucket else None)
        return result

    ma5 = moving_avg(monthly_avgs, 5)

    fig, ax = plt.subplots(figsize=(10, 4))
    x = range(len(months))
    avg_vals = [v if v is not None else float("nan")
                for v in monthly_avgs]
    ma_vals = [v if v is not None else float("nan") for v in ma5]
    ax.plot(x, avg_vals, "o-", color="#ef5350", markersize=4,
            linewidth=1.2, alpha=0.7, label="Monthly avg")
    ax.plot(x, ma_vals, "-", color="#b71c1c", linewidth=2.5,
            label="5-bucket moving avg")
    ax.axhline(y=3.0, color="#999", linestyle="--", linewidth=1.2,
               label="Neutral (3.0)")
    ax.set_xticks(range(0, len(months), 6))
    ax.set_xticklabels([months[i] for i in range(0, len(months), 6)],
                       rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Avg Rating")
    ax.set_ylim(0.5, 5.5)
    ax.set_title("Monthly Average Rating Trend")
    ax.legend(fontsize=9, loc="upper right")
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_stacked_monthly(months, monthly):
    """Stacked bar chart of monthly rating breakdown."""
    fig, ax = plt.subplots(figsize=(10, 3.5))
    x = range(len(months))
    star_order = [1, 2, 3, 4, 5, 0]
    colors = {1: "#ef5350", 2: "#ff9800", 3: "#fdd835",
              4: "#66bb6a", 5: "#43a047", 0: "#e0e0e0"}
    labels_s = {1: "1 Star", 2: "2 Stars", 3: "3 Stars",
                4: "4 Stars", 5: "5 Stars", 0: "No Rating"}
    bottom = np.zeros(len(months))
    for s in star_order:
        vals = np.array([monthly[m][s] for m in months], dtype=float)
        ax.bar(x, vals, bottom=bottom, color=colors[s],
               label=labels_s[s], width=0.85, edgecolor="white",
               linewidth=0.2)
        bottom += vals
    ax.set_xticks(range(0, len(months), 6))
    ax.set_xticklabels([months[i] for i in range(0, len(months), 6)],
                       rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Reviews")
    ax.set_title("Monthly Rating Breakdown (Stacked)")
    ax.legend(fontsize=7, ncol=6, loc="upper left")
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_rolling_avg(reviews):
    """Rolling average rating across all rated reviews."""
    rated_sorted = sorted([r for r in reviews if r["rating"] > 0],
                          key=lambda r: r["date"])
    if len(rated_sorted) < 10:
        return None

    window = max(10, len(rated_sorted) // 40)
    vals = [r["rating"] for r in rated_sorted]
    rolling = []
    for i in range(len(vals)):
        s = max(0, i - window + 1)
        rolling.append(sum(vals[s:i + 1]) / len(vals[s:i + 1]))

    fig, ax = plt.subplots(figsize=(10, 3.5))
    xs = range(len(rolling))
    ax.fill_between(xs, rolling, alpha=0.2, color="#7e57c2")
    ax.plot(xs, rolling, color="#7e57c2", linewidth=1.5)
    ax.axhline(y=3.0, color="#999", linestyle="--", linewidth=1)
    # x-axis date labels
    indices = list(range(0, len(rated_sorted),
                         max(1, len(rated_sorted) // 8)))
    ax.set_xticks(indices)
    ax.set_xticklabels([rated_sorted[i]["date"][:7] for i in indices],
                       rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Rating")
    ax.set_title(f"Rolling Average Rating (window={window} reviews)")
    ax.set_ylim(0, 5.2)
    fig.tight_layout()
    return fig_to_base64(fig)


# ── HTML builder ─────────────────────────────────────────────────────────

CARD = ('background:white;border-radius:10px;padding:24px;'
        'margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.06);')
CARD_HL = CARD + 'border:2px solid #ef5350;'


def build_html(reviews, title="JetBrains Plugin"):
    """Build a complete HTML report with base64-embedded chart images."""
    total = len(reviews)
    rated = [r for r in reviews if r["rating"] > 0]
    avg_all = sum(r["rating"] for r in rated) / len(rated) if rated else 0
    ratings = Counter(r["rating"] for r in reviews)
    dates_all = sorted(set(r["date"] for r in reviews))
    date_min = dates_all[0] if dates_all else "N/A"
    date_max = dates_all[-1] if dates_all else "N/A"

    # Monthly aggregation
    monthly = defaultdict(lambda: {"total": 0, "rated": 0, "sum": 0,
                                   1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 0: 0})
    for r in reviews:
        ym = r["date"][:7]
        monthly[ym]["total"] += 1
        monthly[ym][r["rating"]] += 1
        if r["rating"] > 0:
            monthly[ym]["rated"] += 1
            monthly[ym]["sum"] += r["rating"]
    months = sorted(monthly.keys())

    # Yearly aggregation
    yearly = defaultdict(lambda: {"total": 0, "rated": 0, "sum": 0})
    for r in reviews:
        y = r["date"][:4]
        yearly[y]["total"] += 1
        if r["rating"] > 0:
            yearly[y]["rated"] += 1
            yearly[y]["sum"] += r["rating"]
    years = sorted(yearly.keys())

    # Recent stats
    recent_m = months[-3:] if len(months) >= 3 else months
    recent_total = sum(monthly[m]["total"] for m in recent_m)
    recent_rated = [r for r in reviews
                    if r["date"][:7] in recent_m and r["rating"] > 0]
    recent_avg = (sum(r["rating"] for r in recent_rated)
                  / len(recent_rated) if recent_rated else 0)

    # Render charts
    print("Rendering charts...")
    b64_dist = chart_rating_distribution(reviews)
    b64_year = chart_yearly_avg(reviews)
    b64_vol = chart_monthly_volume(reviews, months, monthly)
    b64_trend = chart_monthly_rating_trend(months, monthly)
    b64_stacked = chart_stacked_monthly(months, monthly)
    b64_rolling = chart_rolling_avg(reviews)
    print("Charts rendered.")

    # Yearly table
    yearly_rows = ""
    for y in years:
        yd = yearly[y]
        avg_y = (f'{yd["sum"] / yd["rated"]:.2f}'
                 if yd["rated"] > 0 else "N/A")
        yearly_rows += (
            f'<tr>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #e8e8e8;">'
            f'{y}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #e8e8e8;">'
            f'{yd["total"]}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #e8e8e8;">'
            f'{yd["rated"]}</td>'
            f'<td style="padding:8px 12px;border-bottom:1px solid #e8e8e8;">'
            f'{avg_y}</td>'
            f'</tr>'
        )

    # Recent reviews
    recent_neg = [r for r in reviews
                  if r["date"][:7] in recent_m and r["rating"] in (1, 2)
                  and r.get("comment")][:8]
    recent_pos = [r for r in reviews
                  if r["date"][:7] in recent_m and r["rating"] == 5
                  and r.get("comment")][:5]

    def review_table(items, color):
        if not items:
            return ('<p style="color:#999;font-size:13px;">'
                    'None found.</p>')
        rows = ""
        for r in items:
            c = html_mod.escape(r.get("comment", ""))[:200]
            if len(r.get("comment", "")) > 200:
                c += "..."
            stars = ("⭐" * r["rating"]) if r["rating"] > 0 else "—"
            link = (f'<a href="{r["link"]}" style="color:#0366d6;">'
                    f'View</a>' if r.get("link") else "")
            rows += (
                f'<tr>'
                f'<td style="padding:6px 8px;border-bottom:1px solid '
                f'#e8e8e8;white-space:nowrap;font-size:12px;">'
                f'{r["date"]}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid '
                f'#e8e8e8;">{stars}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid '
                f'#e8e8e8;font-size:12px;">{c}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid '
                f'#e8e8e8;">{link}</td></tr>'
            )
        return (
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<tr>'
            f'<th style="background:{color};color:white;padding:8px;'
            f'text-align:left;font-size:12px;">Date</th>'
            f'<th style="background:{color};color:white;padding:8px;'
            f'text-align:left;font-size:12px;">Rating</th>'
            f'<th style="background:{color};color:white;padding:8px;'
            f'text-align:left;font-size:12px;">Comment</th>'
            f'<th style="background:{color};color:white;padding:8px;'
            f'text-align:left;font-size:12px;">Link</th></tr>'
            + rows + '</table>'
        )

    # Assemble HTML
    year_chart = (f'<div style="{CARD}">'
                  f'<h2 style="color:#37474f;font-size:16px;'
                  f'margin:0 0 8px 0;">📅 Average Rating by Year</h2>'
                  f'{img_tag(b64_year, "Yearly Average")}</div>'
                  if b64_year else "")
    rolling_chart = (f'<div style="{CARD}">'
                     f'<h2 style="color:#37474f;font-size:16px;'
                     f'margin:0 0 8px 0;">📉 Rolling Average</h2>'
                     f'{img_tag(b64_rolling, "Rolling Average")}</div>'
                     if b64_rolling else "")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:'Segoe UI',Arial,sans-serif;line-height:1.6;\
color:#333;max-width:920px;margin:0 auto;padding:20px;background:#f0f2f5;">

<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);\
padding:28px 24px;border-radius:12px;margin-bottom:20px;">
  <h1 style="color:#fff;margin:0;font-size:22px;">\
📊 {html_mod.escape(title)} — Marketplace Review Report</h1>
  <p style="color:#a0aec0;margin:8px 0 0 0;font-size:13px;">
    Data: <strong style="color:#e2e8f0;">{date_min}</strong> to \
<strong style="color:#e2e8f0;">{date_max}</strong>
    &nbsp;|&nbsp; Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")} UTC
  </p>
</div>

<table style="width:100%;border-collapse:separate;border-spacing:10px 0;\
margin-bottom:16px;">
<tr>
  <td style="background:linear-gradient(135deg,#667eea,#764ba2);\
color:white;border-radius:10px;padding:14px;text-align:center;width:25%;">
    <div style="font-size:24px;font-weight:bold;">{total}</div>\
<div style="font-size:10px;opacity:0.9;">Total Reviews</div></td>
  <td style="background:linear-gradient(135deg,#f093fb,#f5576c);\
color:white;border-radius:10px;padding:14px;text-align:center;width:25%;">
    <div style="font-size:24px;font-weight:bold;">{avg_all:.2f}</div>\
<div style="font-size:10px;opacity:0.9;">Avg Rating</div></td>
  <td style="background:linear-gradient(135deg,#4facfe,#00f2fe);\
color:white;border-radius:10px;padding:14px;text-align:center;width:25%;">
    <div style="font-size:24px;font-weight:bold;">{recent_total}</div>\
<div style="font-size:10px;opacity:0.9;">Last 3 Months</div></td>
  <td style="background:linear-gradient(135deg,#43e97b,#38f9d7);\
color:white;border-radius:10px;padding:14px;text-align:center;width:25%;">
    <div style="font-size:24px;font-weight:bold;">{recent_avg:.2f}</div>\
<div style="font-size:10px;opacity:0.9;">Recent Avg</div></td>
</tr></table>

<div style="{CARD}">
  <h2 style="color:#37474f;font-size:16px;margin:0 0 8px 0;">\
📊 Rating Distribution</h2>
  {img_tag(b64_dist, "Rating Distribution")}
</div>

{year_chart}

<div style="{CARD}">
  <h2 style="color:#37474f;font-size:16px;margin:0 0 8px 0;">\
📈 Monthly Review Volume</h2>
  {img_tag(b64_vol, "Monthly Volume")}
</div>

<div style="{CARD_HL}">
  <h2 style="color:#ef5350;font-size:16px;margin:0 0 8px 0;">\
⭐ Monthly Average Rating Trend</h2>
  {img_tag(b64_trend, "Monthly Rating Trend")}
</div>

<div style="{CARD}">
  <h2 style="color:#37474f;font-size:16px;margin:0 0 8px 0;">\
🎯 Monthly Rating Breakdown (Stacked)</h2>
  {img_tag(b64_stacked, "Stacked Breakdown")}
</div>

{rolling_chart}

<div style="{CARD}">
  <h2 style="color:#37474f;font-size:16px;margin:0 0 12px 0;">\
📅 Yearly Summary</h2>
  <table style="width:100%;border-collapse:collapse;">
  <tr>\
<th style="background:#4361ee;color:white;padding:10px 12px;\
text-align:left;">Year</th>\
<th style="background:#4361ee;color:white;padding:10px 12px;\
text-align:left;">Total</th>\
<th style="background:#4361ee;color:white;padding:10px 12px;\
text-align:left;">Rated</th>\
<th style="background:#4361ee;color:white;padding:10px 12px;\
text-align:left;">Avg Rating</th></tr>
  {yearly_rows}
  </table>
</div>

<div style="{CARD}">
  <h2 style="color:#ef5350;font-size:16px;margin:0 0 12px 0;">\
🔴 Recent Negative Feedback (1-2 ⭐, Last 3 Months)</h2>
  {review_table(recent_neg, "#ef5350")}
</div>

<div style="{CARD}">
  <h2 style="color:#43a047;font-size:16px;margin:0 0 12px 0;">\
🟢 Recent Positive Highlights (5 ⭐, Last 3 Months)</h2>
  {review_table(recent_pos, "#43a047")}
</div>

<div style="text-align:center;color:#999;font-size:11px;padding:15px 0;">
  IssueLens — JetBrains Marketplace Review Analytics \
&nbsp;|&nbsp; Auto-generated report
</div>

</body></html>"""
    return html


# ── main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Render review charts as base64 PNGs in HTML")
    parser.add_argument("--input", type=str, default=None,
                        help="Input JSON file path")
    parser.add_argument("--output", type=str, default=None,
                        help="Output HTML file path")
    parser.add_argument("--title", type=str, default="JetBrains Plugin",
                        help="Plugin name shown in titles")
    parser.add_argument("--json-output", type=str, default=None,
                        help="Also save individual chart base64 data "
                             "as a JSON file")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    input_file = (Path(args.input) if args.input
                  else script_dir / "reviews.json")
    output_file = (Path(args.output) if args.output
                   else script_dir / "email_report.html")

    reviews = load_reviews(input_file)
    print(f"Loaded {len(reviews)} reviews")

    html = build_html(reviews, args.title)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML report saved to: {output_file}")
    print(f"Report size: {len(html):,} chars")

    if args.json_output:
        # Also export individual chart images as JSON for custom use
        from collections import OrderedDict
        monthly = defaultdict(lambda: {"total": 0, "rated": 0, "sum": 0,
                                       1: 0, 2: 0, 3: 0, 4: 0, 5: 0,
                                       0: 0})
        for r in reviews:
            ym = r["date"][:7]
            monthly[ym]["total"] += 1
            monthly[ym][r["rating"]] += 1
            if r["rating"] > 0:
                monthly[ym]["rated"] += 1
                monthly[ym]["sum"] += r["rating"]
        months = sorted(monthly.keys())

        charts = OrderedDict()
        charts["rating_distribution"] = chart_rating_distribution(reviews)
        b64_year = chart_yearly_avg(reviews)
        if b64_year:
            charts["yearly_avg"] = b64_year
        charts["monthly_volume"] = chart_monthly_volume(
            reviews, months, monthly)
        charts["rating_trend"] = chart_monthly_rating_trend(
            months, monthly)
        charts["stacked_breakdown"] = chart_stacked_monthly(
            months, monthly)
        b64_rolling = chart_rolling_avg(reviews)
        if b64_rolling:
            charts["rolling_avg"] = b64_rolling

        json_path = Path(args.json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(charts, f)
        print(f"Chart JSON saved to: {json_path} ({len(charts)} charts)")


if __name__ == "__main__":
    main()
