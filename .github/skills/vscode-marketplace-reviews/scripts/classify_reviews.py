#!/usr/bin/env python3
"""
Semantically classify VS Code Marketplace reviews into user-defined
categories using the GitHub Models API (LLM-based classification).

Categories are provided via the ``--category`` flag, each as a
``"Name: Description"`` pair.  An implicit **"Others"** category is
always appended as the fallback.

Usage:
    py classify_reviews.py \
      --input reviews.json --output classified.json \
      --category "Performance: Extension is slow, laggy, or uses high CPU/memory" \
      --category "Rate Limiting: User complains about rate limits or token usage" \
      --category "Crash: IDE crashes or extension fails to load"

Environment:
    GITHUB_TOKEN  — GitHub PAT (used for the GitHub Models inference API)
"""

import json
import os
import sys
import time
import argparse
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path

BATCH_SIZE = 40
MODEL = "gpt-4o-mini"
API_URL = "https://models.inference.ai.azure.com/chat/completions"


# ── prompt builder ───────────────────────────────────────────────────────

def build_system_prompt(categories: list[tuple[str, str]]) -> str:
    """Build a system prompt from user-supplied category definitions."""
    lines = [
        "You are a review classifier. For each review comment, "
        "determine which of these issue categories apply:\n"
    ]
    for i, (name, desc) in enumerate(categories, 1):
        lines.append(f'{i}. "{name}" — {desc}')

    others_idx = len(categories) + 1
    lines.append(
        f'{others_idx}. "Others" — The comment does not match any of '
        f"the above categories."
    )

    lines.append(
        "\nRules:\n"
        "- A review can match MULTIPLE categories "
        '(e.g. both "Performance" and "Crash").\n'
        "- If none of the defined categories apply, "
        'assign "Others".\n'
        '- "Others" should NOT be combined with other categories.\n'
        "- Base your decision on the semantic meaning, not just "
        "keywords.\n"
        "\nRespond with ONLY a JSON array where each element is an "
        'object with "id" (the review id) and "category" (array of '
        "matching category strings). No other text."
    )
    return "\n".join(lines)


# ── API helpers ──────────────────────────────────────────────────────────

def call_api(token: str, messages: list) -> str | None:
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 4096,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(30, 5 * (attempt + 1))
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < 2:
                print(f"  Retry {attempt + 1}: {e}")
                time.sleep(3)
                continue
            raise
    return None


def classify_batch(token: str, batch: list,
                   system_prompt: str) -> dict:
    """Classify a batch of reviews. Returns ``{id: [categories]}``."""
    user_content = "Classify these reviews:\n\n"
    for r in batch:
        comment = r.get("comment", "")[:500]
        user_content += f'ID={r["id"]}: """{comment}"""\n\n'

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    raw = call_api(token, messages)
    if not raw:
        return {}

    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        print("  Warning: Failed to parse LLM response, "
              "skipping batch")
        return {}

    result = {}
    for item in items:
        rid = item.get("id")
        cats = item.get("category", ["Others"])
        if isinstance(cats, str):
            cats = [cats]
        result[rid] = cats
    return result


# ── main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Semantically classify reviews into "
                    "user-defined categories via LLM")
    parser.add_argument(
        "--input", type=str, default=None,
        help="Input JSON file path")
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON file path (default: same as --input)")
    parser.add_argument(
        "--category", type=str, action="append", default=[],
        metavar='"Name: Description"',
        help="Category definition as 'Name: Description'. "
             "Repeat for each category. An implicit 'Others' "
             "fallback is always added.")
    parser.add_argument(
        "--batch-size", type=int, default=BATCH_SIZE,
        help=f"Reviews per API call (default: {BATCH_SIZE})")
    args = parser.parse_args()

    # Resolve paths
    script_dir = Path(__file__).parent
    default_path = script_dir / ".." / ".." / ".." / ".." / "output" \
        / "reviews.json"
    input_file = Path(args.input) if args.input else default_path
    output_file = Path(args.output) if args.output else input_file

    # Parse categories
    categories: list[tuple[str, str]] = []
    for entry in args.category:
        if ":" in entry:
            name, desc = entry.split(":", 1)
            categories.append((name.strip(), desc.strip()))
        else:
            categories.append((entry.strip(),
                               f"Reviews related to {entry.strip()}"))

    if not categories:
        parser.error(
            "At least one --category is required.\n"
            "  Example: --category "
            '"Performance: Extension is slow or uses high CPU"')

    # Load
    with open(input_file, "r", encoding="utf-8") as f:
        reviews = json.load(f)
    print(f"Loaded {len(reviews)} reviews from {input_file}")

    # Filter to reviews with comments
    to_classify = [r for r in reviews if r.get("comment")]
    print(f"Classifying {len(to_classify)} reviews with comments...")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable is required")
        sys.exit(1)

    system_prompt = build_system_prompt(categories)

    # Process in batches
    results = {}
    for i in range(0, len(to_classify), args.batch_size):
        batch = to_classify[i:i + args.batch_size]
        print(f"  Batch {i // args.batch_size + 1} "
              f"({len(batch)} reviews)...")
        batch_result = classify_batch(token, batch, system_prompt)
        results.update(batch_result)

    # Merge results back into reviews
    classified = 0
    for r in reviews:
        if r["id"] in results:
            r["category"] = results[r["id"]]
            classified += 1
        elif not r.get("comment"):
            r["category"] = ["Others"]

    print(f"Classified {classified}/{len(to_classify)} reviews")

    # Category summary
    all_cats = Counter()
    for r in reviews:
        for cat in r.get("category", []):
            all_cats[cat] += 1

    print("\nCategory distribution:")
    for cat, count in all_cats.most_common():
        print(f"  {cat}: {count}")

    # Save
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {output_file}")


if __name__ == "__main__":
    main()
