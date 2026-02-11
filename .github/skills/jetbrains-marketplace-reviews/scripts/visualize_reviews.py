#!/usr/bin/env python3
"""
Visualize JetBrains Marketplace Plugin Reviews.

Reads review JSON data and generates charts that adapt to the time scope:
  - Short range  (<=30 days):  daily granularity, 4-panel layout
  - Medium range (<=365 days): weekly granularity, 4-panel layout
  - Long range   (>365 days):  monthly granularity, 6-panel layout

Usage:
    py visualize_reviews.py --input reviews.json --output chart.png [--title "Plugin Name"] [--no-show]
"""

import json
import io
import base64
import argparse
from datetime import datetime, timedelta
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


def fig_to_base64(fig, dpi=150):
    """Render a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


# ── helpers ──────────────────────────────────────────────────────────────

def load_reviews(filepath: str) -> list:
    """Load reviews from JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def detect_scope(reviews: list) -> str:
    """Return 'short', 'medium', or 'long' based on date span."""
    dates = sorted(r["date"] for r in reviews)
    if not dates:
        return "short"
    span = (datetime.strptime(dates[-1], "%Y-%m-%d")
            - datetime.strptime(dates[0], "%Y-%m-%d")).days
    if span <= 30:
        return "short"
    if span <= 365:
        return "medium"
    return "long"


def bucket_key(date_str: str, scope: str) -> str:
    """Return the aggregation bucket key for a date."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if scope == "short":
        return date_str                         # daily
    if scope == "medium":
        # ISO week: Monday-based
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"        # weekly
    return date_str[:7]                          # monthly (YYYY-MM)


def bucket_to_date(key: str, scope: str) -> datetime:
    """Convert a bucket key back to a datetime for plotting."""
    if scope == "short":
        return datetime.strptime(key, "%Y-%m-%d")
    if scope == "medium":
        # Parse ISO week to Monday date
        return datetime.strptime(key + "-1", "%G-W%V-%u")
    return datetime.strptime(key + "-15", "%Y-%m-%d")


def scope_label(scope: str) -> str:
    return {"short": "Daily", "medium": "Weekly", "long": "Monthly"}[scope]


# ── summary ──────────────────────────────────────────────────────────────

def print_summary(reviews: list, title: str = "JetBrains Plugin") -> None:
    """Print summary statistics to console."""
    total = len(reviews)
    ratings = [r["rating"] for r in reviews]
    rated = [r for r in ratings if r > 0]
    avg = sum(rated) / len(rated) if rated else 0
    with_replies = sum(1 for r in reviews if r.get("has_replies"))

    print("\n" + "=" * 50)
    print(f"{title.upper()} - REVIEW SUMMARY")
    print("=" * 50)
    print(f"Total Reviews: {total}")
    print(f"Average Rating: {avg:.2f} / 5.0 (excluding unrated)")
    print(f"Reviews with Replies: {with_replies} "
          f"({with_replies / total * 100:.1f}%)")

    rc = Counter(ratings)
    print("\nRating Breakdown:")
    for star in sorted(rc.keys(), reverse=True):
        count = rc[star]
        label = "No Rating" if star == 0 else f"{star} Star(s)"
        bar = "#" * min(count, 60)
        print(f"  {label:>12}: {bar} ({count})")
    print("=" * 50 + "\n")


# ── plot functions ───────────────────────────────────────────────────────

def plot_rating_distribution(reviews, ax):
    """Bar chart of rating counts."""
    rc = Counter(r["rating"] for r in reviews)
    labels = ["No Rating", "1 Star", "2 Stars", "3 Stars", "4 Stars",
              "5 Stars"]
    counts = [rc.get(i, 0) for i in range(6)]
    colors = ["#bdc3c7", "#e74c3c", "#e67e22", "#f1c40f", "#2ecc71",
              "#27ae60"]

    bars = ax.bar(labels, counts, color=colors, edgecolor="black",
                  linewidth=0.5)
    for bar, count in zip(bars, counts):
        if count > 0:
            pct = count / len(reviews) * 100
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.5,
                    f"{count}\n({pct:.1f}%)", ha="center", va="bottom",
                    fontsize=8, fontweight="bold")
    ax.set_ylabel("Count")
    ax.set_title("Rating Distribution", fontweight="bold")
    ax.tick_params(axis="x", rotation=30)


def plot_volume(reviews, ax, scope):
    """Bar chart of review volume per time bucket."""
    buckets = Counter(bucket_key(r["date"], scope) for r in reviews)
    keys = sorted(buckets.keys())
    dates = [bucket_to_date(k, scope) for k in keys]
    counts = [buckets[k] for k in keys]

    width = {"short": 0.8, "medium": 5, "long": 25}[scope]
    ax.bar(dates, counts, width=width, color="#3498db", edgecolor="black",
           linewidth=0.3, alpha=0.8)
    ax.set_ylabel("Reviews")
    ax.set_title(f"{scope_label(scope)} Review Volume", fontweight="bold")
    _format_date_axis(ax, scope, keys)


def plot_rating_trend(reviews, ax, scope):
    """Line chart of average rating per time bucket with smoothing."""
    bucket_ratings = defaultdict(list)
    for r in reviews:
        if r["rating"] > 0:
            bucket_ratings[bucket_key(r["date"], scope)].append(r["rating"])

    keys = sorted(bucket_ratings.keys())
    if not keys:
        ax.text(0.5, 0.5, "No rated reviews", ha="center", va="center",
                transform=ax.transAxes)
        return

    dates = [bucket_to_date(k, scope) for k in keys]
    avgs = [np.mean(bucket_ratings[k]) for k in keys]

    ax.plot(dates, avgs, marker="o", markersize=3, linewidth=1,
            color="#e74c3c", alpha=0.5, label=f"{scope_label(scope)} avg")

    # Smoothing line (window adapts to scope)
    win = max(3, len(avgs) // 10)
    if len(avgs) > win:
        from scipy.ndimage import uniform_filter1d
        smoothed = uniform_filter1d(np.array(avgs, dtype=float), size=win)
        ax.plot(dates, smoothed, linewidth=2.5, color="#c0392b",
                label=f"{win}-bucket moving avg")

    ax.axhline(y=3.0, color="gray", linestyle="--", alpha=0.5,
               label="Neutral (3.0)")
    ax.set_ylabel("Avg Rating")
    ax.set_title(f"{scope_label(scope)} Average Rating Trend",
                 fontweight="bold")
    ax.set_ylim(0, 5.5)
    ax.legend(fontsize=7)
    _format_date_axis(ax, scope, keys)


def plot_reply_rate(reviews, ax):
    """Bar chart of reply rate by star rating."""
    groups = defaultdict(lambda: {"total": 0, "replied": 0})
    for r in reviews:
        groups[r["rating"]]["total"] += 1
        if r.get("has_replies"):
            groups[r["rating"]]["replied"] += 1

    colors = ["#bdc3c7", "#e74c3c", "#e67e22", "#f1c40f", "#2ecc71",
              "#27ae60"]
    labels, rates, bar_colors = [], [], []
    for star in range(6):
        if groups[star]["total"] > 0:
            labels.append("No Rating" if star == 0 else f"{star} Star(s)")
            rates.append(groups[star]["replied"]
                         / groups[star]["total"] * 100)
            bar_colors.append(colors[star])

    bars = ax.bar(labels, rates, color=bar_colors, edgecolor="black",
                  linewidth=0.5)
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{rate:.0f}%", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Reply Rate (%)")
    ax.set_title("Reply Rate by Rating", fontweight="bold")
    ax.set_ylim(0, 100)
    ax.tick_params(axis="x", rotation=30)


def plot_stacked_breakdown(reviews, ax, scope):
    """Stacked area chart of rating composition over time."""
    bucket_stars = defaultdict(lambda: Counter())
    for r in reviews:
        bucket_stars[bucket_key(r["date"], scope)][r["rating"]] += 1

    keys = sorted(bucket_stars.keys())
    dates = [bucket_to_date(k, scope) for k in keys]
    categories = [1, 2, 3, 4, 5, 0]
    cat_labels = ["1 Star", "2 Stars", "3 Stars", "4 Stars", "5 Stars",
                  "No Rating"]
    cat_colors = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#27ae60",
                  "#bdc3c7"]

    stacks = [np.array([bucket_stars[k].get(s, 0) for k in keys])
              for s in categories]
    ax.stackplot(dates, *stacks, labels=cat_labels, colors=cat_colors,
                 alpha=0.85)
    ax.set_ylabel("Reviews")
    ax.set_title(f"{scope_label(scope)} Rating Breakdown (Stacked)",
                 fontweight="bold")
    ax.legend(loc="upper left", fontsize=7, ncol=3)
    _format_date_axis(ax, scope, keys)


def plot_rolling_avg(reviews, ax):
    """Rolling average rating across all rated reviews."""
    rated = sorted([r for r in reviews if r["rating"] > 0],
                   key=lambda x: x["date"])
    if len(rated) < 10:
        ax.text(0.5, 0.5, "Not enough data", ha="center", va="center",
                transform=ax.transAxes)
        return

    window = max(10, len(rated) // 40)
    dates, avgs = [], []
    for i in range(window, len(rated)):
        chunk = rated[i - window:i]
        dates.append(datetime.strptime(chunk[-1]["date"], "%Y-%m-%d"))
        avgs.append(np.mean([c["rating"] for c in chunk]))

    ax.plot(dates, avgs, linewidth=1.5, color="#8e44ad", alpha=0.8)
    ax.fill_between(dates, avgs, alpha=0.15, color="#8e44ad")
    ax.axhline(y=3.0, color="gray", linestyle="--", alpha=0.5)
    ax.set_ylabel("Rating")
    ax.set_title(f"Rolling Average Rating (window={window} reviews)",
                 fontweight="bold")
    ax.set_ylim(0, 5.5)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")


def plot_yearly_avg(reviews, ax):
    """Bar chart of average rating by year."""
    yearly = defaultdict(list)
    yearly_total = defaultdict(int)
    for r in reviews:
        yr = r["date"][:4]
        yearly_total[yr] += 1
        if r["rating"] > 0:
            yearly[yr].append(r["rating"])

    years = sorted(yearly.keys())
    avgs = [np.mean(yearly[y]) for y in years]
    totals = [yearly_total[y] for y in years]
    colors = ["#27ae60" if a >= 3.5 else "#f1c40f" if a >= 2.5
              else "#e67e22" if a >= 2.0 else "#e74c3c" for a in avgs]

    bars = ax.bar(years, avgs, color=colors, edgecolor="black",
                  linewidth=0.5)
    for bar, avg, n in zip(bars, avgs, totals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.08,
                f"{avg:.2f}\n(n={n})", ha="center", va="bottom", fontsize=8,
                fontweight="bold")
    ax.set_ylabel("Average Rating")
    ax.set_title("Average Rating by Year", fontweight="bold")
    ax.set_ylim(0, 5.2)
    ax.axhline(y=3.0, color="gray", linestyle="--", alpha=0.5)


# ── axis formatting ─────────────────────────────────────────────────────

def _format_date_axis(ax, scope, keys):
    fmt_map = {"short": "%m/%d", "medium": "%Y-%m", "long": "%Y-%m"}
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt_map[scope]))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")


# ── base64 chart rendering ───────────────────────────────────────────────

def _render_individual_charts(reviews, scope, title):
    """Render each chart as a standalone figure and return a dict of
    ``{chart_name: base64_png_string}`` pairs.

    This is used by the ``--base64`` flag to produce email-embeddable
    chart images that can be inlined as::

        <img src="data:image/png;base64,{value}" />
    """
    charts = {}

    # 1. Rating Distribution
    fig, ax = plt.subplots(figsize=(7, 3.5))
    plot_rating_distribution(reviews, ax)
    fig.tight_layout()
    charts["rating_distribution"] = fig_to_base64(fig)

    # 2. Review Volume
    fig, ax = plt.subplots(figsize=(10, 3))
    plot_volume(reviews, ax, scope)
    fig.tight_layout()
    charts["review_volume"] = fig_to_base64(fig)

    # 3. Rating Trend (key chart)
    fig, ax = plt.subplots(figsize=(10, 4))
    plot_rating_trend(reviews, ax, scope)
    fig.tight_layout()
    charts["rating_trend"] = fig_to_base64(fig)

    # 4. Reply Rate
    fig, ax = plt.subplots(figsize=(7, 3.5))
    plot_reply_rate(reviews, ax)
    fig.tight_layout()
    charts["reply_rate"] = fig_to_base64(fig)

    # Long-range extras
    if scope == "long":
        # 5. Yearly Average
        fig, ax = plt.subplots(figsize=(7, 3.5))
        plot_yearly_avg(reviews, ax)
        fig.tight_layout()
        charts["yearly_avg"] = fig_to_base64(fig)

        # 6. Stacked Breakdown
        fig, ax = plt.subplots(figsize=(10, 3.5))
        plot_stacked_breakdown(reviews, ax, scope)
        fig.tight_layout()
        charts["stacked_breakdown"] = fig_to_base64(fig)

        # 7. Rolling Average
        fig, ax = plt.subplots(figsize=(10, 3.5))
        plot_rolling_avg(reviews, ax)
        fig.tight_layout()
        charts["rolling_avg"] = fig_to_base64(fig)

    return charts


# ── main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Visualize JetBrains Marketplace plugin reviews")
    parser.add_argument("--input", type=str, default=None,
                        help="Input JSON file path")
    parser.add_argument("--output", type=str, default=None,
                        help="Output PNG file path")
    parser.add_argument("--title", type=str, default="JetBrains Plugin",
                        help="Plugin name shown in chart titles")
    parser.add_argument("--no-show", action="store_true",
                        help="Don't display the plot")
    parser.add_argument("--base64", action="store_true",
                        help="Output each chart as a base64 PNG string "
                             "(JSON dict) instead of a single image file. "
                             "Useful for embedding charts in HTML emails.")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    input_file = (Path(args.input) if args.input
                  else script_dir / "reviews.json")
    output_file = (Path(args.output) if args.output
                   else script_dir / "review_analysis.png")

    reviews = load_reviews(input_file)
    scope = detect_scope(reviews)
    print(f"Detected scope: {scope} "
          f"({len(reviews)} reviews)")

    print_summary(reviews, args.title)

    # ── Base64 mode: render each chart individually ──
    if args.base64:
        charts = _render_individual_charts(reviews, scope, args.title)
        output_json = output_file.with_suffix(".json")
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(charts, f)
        print(f"Base64 charts saved to: {output_json} "
              f"({len(charts)} charts)")
        return

    chart_title = (f"{args.title} – Review Analysis"
                   f" ({len(reviews)} reviews)")

    # Layout adapts: 6-panel for long range, 4-panel otherwise
    if scope == "long":
        fig = plt.figure(figsize=(20, 16))
        fig.suptitle(chart_title,
                     fontsize=16, fontweight="bold", y=0.99)

        ax1 = fig.add_subplot(3, 2, 1)
        ax2 = fig.add_subplot(3, 2, 2)
        ax3 = fig.add_subplot(3, 2, 3)
        ax4 = fig.add_subplot(3, 2, 4)
        ax5 = fig.add_subplot(3, 2, 5)
        ax6 = fig.add_subplot(3, 2, 6)

        plot_rating_distribution(reviews, ax1)
        plot_yearly_avg(reviews, ax2)
        plot_volume(reviews, ax3, scope)
        plot_rating_trend(reviews, ax4, scope)
        plot_stacked_breakdown(reviews, ax5, scope)
        plot_rolling_avg(reviews, ax6)
    else:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(chart_title,
                     fontsize=14, fontweight="bold")

        plot_rating_distribution(reviews, axes[0, 0])
        plot_volume(reviews, axes[0, 1], scope)
        plot_reply_rate(reviews, axes[1, 0])
        plot_rating_trend(reviews, axes[1, 1], scope)

    plt.tight_layout(rect=[0, 0, 1, 0.95])

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    print(f"Chart saved to: {output_file}")

    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
