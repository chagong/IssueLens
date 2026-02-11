#!/usr/bin/env python3
"""
Fetch and parse JetBrains Marketplace plugin reviews from API.
Supports any plugin ID and any time scope via pagination.

Usage:
    py fetch_reviews.py --output reviews.json [OPTIONS]

Time scope options (mutually exclusive):
    --all               Fetch all reviews from the beginning
    --weeks N           Fetch last N weeks of reviews (default: 3)
    --since YYYY-MM-DD  Fetch reviews from this date onward
    --since YYYY-MM-DD --until YYYY-MM-DD  Fetch reviews in date range

Plugin options:
    --plugin-id ID      JetBrains plugin numeric ID (default: 17718)
    --plugin-slug SLUG  Plugin URL slug for review links
                        (default: github-copilot--your-ai-pair-programmer)

Other options:
    --output PATH       Output JSON file path (default: reviews.json in script dir)
    --full-content      Include author name and review comment text
"""

import json
import re
import urllib.request
import argparse
from datetime import datetime, timedelta
from pathlib import Path

PLUGIN_ID_DEFAULT = 17718
PLUGIN_SLUG_DEFAULT = "github-copilot--your-ai-pair-programmer"
PAGE_SIZE = 100
REVIEW_URL_TEMPLATE = (
    "https://plugins.jetbrains.com/plugin/{plugin_id}-{plugin_slug}"
    "/reviews#review={review_id}"
)


def fetch_all_pages(plugin_id: int = PLUGIN_ID_DEFAULT,
                    since: str = None) -> list:
    """Fetch reviews from JetBrains API with pagination.

    Iterates through all pages until no more results are returned
    or all remaining reviews are older than ``since``.
    """
    all_reviews = []
    page = 1

    while True:
        url = (
            f"https://plugins.jetbrains.com/api/plugins/"
            f"{plugin_id}/comments?size={PAGE_SIZE}&page={page}"
        )
        print(f"Fetching page {page} ...")
        req = urllib.request.Request(
            url, headers={"Accept": "application/json",
                          "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data:
            break

        all_reviews.extend(data)

        # Early exit when we've passed the since cutoff
        if since:
            oldest_ts = int(data[-1].get("cdate", "0"))
            oldest_date = datetime.fromtimestamp(
                oldest_ts / 1000).strftime("%Y-%m-%d")
            if oldest_date < since:
                break

        if len(data) < PAGE_SIZE:
            break
        page += 1

    print(f"Fetched {len(all_reviews)} raw reviews across {page} page(s)")
    return all_reviews


def parse_review(raw: dict, plugin_id: int = PLUGIN_ID_DEFAULT,
                 plugin_slug: str = PLUGIN_SLUG_DEFAULT,
                 full_content: bool = False) -> dict:
    """Parse a single raw API review into a structured object."""
    timestamp_ms = int(raw.get("cdate", "0"))
    date = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d")

    comment_html = raw.get("comment", "") or ""
    comment_text = re.sub(r"<[^>]+>", "", comment_html).strip()

    review = {
        "id": raw["id"],
        "date": date,
        "rating": raw.get("rating", 0),
        "comment": comment_text,
        "has_replies": raw.get("repliesCount", 0) > 0,
        "link": REVIEW_URL_TEMPLATE.format(
            plugin_id=plugin_id, plugin_slug=plugin_slug,
            review_id=raw["id"]),
    }

    if full_content:
        author_obj = raw.get("author") or {}
        review["author"] = author_obj.get("name", "Anonymous")

    return review


def filter_reviews(reviews: list, since: str = None,
                   until: str = None) -> list:
    """Filter reviews by date range (inclusive)."""
    filtered = reviews
    if since:
        filtered = [r for r in filtered if r["date"] >= since]
    if until:
        filtered = [r for r in filtered if r["date"] <= until]
    return filtered


def save_reviews(reviews: list, filepath: Path) -> None:
    """Save reviews to JSON file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(reviews)} reviews to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch JetBrains Marketplace plugin reviews")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true",
                       help="Fetch all reviews from the beginning")
    scope.add_argument("--weeks", type=int, default=None,
                       help="Number of weeks of data to fetch")
    parser.add_argument("--since", type=str, default=None,
                        help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--until", type=str, default=None,
                        help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--plugin-id", type=int, default=PLUGIN_ID_DEFAULT,
                        help="JetBrains plugin numeric ID")
    parser.add_argument("--plugin-slug", type=str,
                        default=PLUGIN_SLUG_DEFAULT,
                        help="Plugin URL slug (for review links)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    parser.add_argument("--full-content", action="store_true",
                        help="Include author and comment text")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    output_file = (Path(args.output) if args.output
                   else script_dir / "reviews.json")

    # Determine the since cutoff for pagination optimisation
    fetch_all = args.all
    since_cutoff = args.since

    if not fetch_all and args.weeks is None and args.since is None:
        # Default to 3 weeks when no scope is specified
        args.weeks = 3

    if args.weeks is not None:
        since_cutoff = (
            datetime.now() - timedelta(weeks=args.weeks)
        ).strftime("%Y-%m-%d")

    # Fetch (paginated) and parse
    raw_reviews = fetch_all_pages(
        plugin_id=args.plugin_id,
        since=None if fetch_all else since_cutoff,
    )
    parsed = [parse_review(r, args.plugin_id, args.plugin_slug,
                           args.full_content)
              for r in raw_reviews]

    # Apply date filters
    parsed = filter_reviews(parsed, since=since_cutoff, until=args.until)

    # Sort by date descending
    parsed.sort(key=lambda x: (x["date"], x["id"]), reverse=True)

    save_reviews(parsed, output_file)

    if parsed:
        print(f"\nDate range: {parsed[-1]['date']} to {parsed[0]['date']}")
    print(f"Total reviews: {len(parsed)}")
    return output_file


if __name__ == "__main__":
    main()
