#!/usr/bin/env python3
"""
Fetch and parse VS Code Marketplace extension reviews from API.
Supports any extension (publisher.name) and any time scope via pagination.

Usage:
    py fetch_reviews.py --output reviews.json [OPTIONS]

Time scope options (mutually exclusive):
    --all               Fetch all reviews from the beginning
    --weeks N           Fetch last N weeks of reviews (default: 3)
    --since YYYY-MM-DD  Fetch reviews from this date onward
    --since YYYY-MM-DD --until YYYY-MM-DD  Fetch reviews in date range

Extension options:
    --publisher PUB     Publisher name (default: GitHub)
    --extension EXT     Extension name (default: copilot-chat)

Other options:
    --output PATH       Output JSON file path
    --full-content      Include author display name in output
"""

import json
import argparse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PUBLISHER_DEFAULT = "GitHub"
EXTENSION_DEFAULT = "copilot-chat"
PAGE_SIZE = 100
REVIEW_URL_TEMPLATE = (
    "https://marketplace.visualstudio.com/items?"
    "itemName={publisher}.{extension}&ssr=false#review-details"
)
API_URL_TEMPLATE = (
    "https://marketplace.visualstudio.com/_apis/public/gallery/"
    "publishers/{publisher}/extensions/{extension}/reviews"
)
API_VERSION = "7.2-preview.1"


def fetch_all_pages(publisher: str = PUBLISHER_DEFAULT,
                    extension: str = EXTENSION_DEFAULT,
                    since: str = None) -> list:
    """Fetch reviews from VS Code Marketplace API with pagination.

    Uses the ``beforeDate`` parameter to paginate through pages of
    reviews (newest first, up to PAGE_SIZE per request).
    """
    all_reviews = []
    before_date = None

    while True:
        url = (
            f"{API_URL_TEMPLATE.format(publisher=publisher, extension=extension)}"
            f"?filterOptions=1&count={PAGE_SIZE}"
            f"&api-version={API_VERSION}"
        )
        if before_date:
            url += f"&beforeDate={before_date}"

        print(f"Fetching page (before={before_date or 'latest'}) ...")
        req = urllib.request.Request(
            url, headers={"Accept": "application/json",
                          "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        reviews = data.get("reviews", [])
        if not reviews:
            break

        all_reviews.extend(reviews)

        # Early exit when we've passed the since cutoff
        if since:
            oldest_date = reviews[-1].get("updatedDate", "")[:10]
            if oldest_date < since:
                break

        has_more = data.get("hasMoreReviews", False)
        if not has_more:
            break

        # Use the last review's date for pagination
        before_date = reviews[-1]["updatedDate"]

    print(f"Fetched {len(all_reviews)} raw reviews")
    return all_reviews


def parse_review(raw: dict, publisher: str = PUBLISHER_DEFAULT,
                 extension: str = EXTENSION_DEFAULT,
                 full_content: bool = False) -> dict:
    """Parse a single raw API review into a structured object."""
    updated = raw.get("updatedDate", "")
    date = updated[:10] if updated else ""

    review = {
        "id": raw["id"],
        "date": date,
        "rating": raw.get("rating", 0),
        "comment": (raw.get("text") or "").strip(),
        "productVersion": raw.get("productVersion", ""),
        "link": REVIEW_URL_TEMPLATE.format(
            publisher=publisher, extension=extension),
    }

    if full_content:
        review["author"] = raw.get("userDisplayName", "Anonymous")

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
        description="Fetch VS Code Marketplace extension reviews")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true",
                       help="Fetch all reviews from the beginning")
    scope.add_argument("--weeks", type=int, default=None,
                       help="Number of weeks of data to fetch")
    parser.add_argument("--since", type=str, default=None,
                        help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--until", type=str, default=None,
                        help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--publisher", type=str, default=PUBLISHER_DEFAULT,
                        help="Extension publisher name")
    parser.add_argument("--extension", type=str, default=EXTENSION_DEFAULT,
                        help="Extension name")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    parser.add_argument("--full-content", action="store_true",
                        help="Include author display name")
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
        publisher=args.publisher,
        extension=args.extension,
        since=None if fetch_all else since_cutoff,
    )
    parsed = [parse_review(r, args.publisher, args.extension,
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
