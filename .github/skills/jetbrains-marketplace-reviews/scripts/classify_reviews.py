#!/usr/bin/env python3
"""
Semantically classify JetBrains Marketplace reviews into user-defined
categories using the GitHub Models API (LLM-based classification).

Categories are provided via the ``--category`` flag, each as a
``"Name: Description"`` pair.  An implicit **"Others"** category is
always appended as the fallback.

Usage:
    py classify_reviews.py \
      --input reviews.json --output classified.json \
      --category "Freeze / Hang: IDE or plugin becomes unresponsive" \
      --category "Crash: IDE crashes or terminates unexpectedly" \
      --category "Startup Failure: Plugin fails to start or initialize"

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
    """Build a system prompt from user-supplied category definitions.

    *categories* is a list of ``(name, description)`` tuples.
    """
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
        '(e.g. both "Freeze / Hang" and "Crash").\n'
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
        help="Input JSON file path "
             "(default: <skill>/scripts/reviews.json)")
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON file path "
             "(default: same as --input, overwritten in-place)")
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
            '"Freeze / Hang: IDE becomes unresponsive"')

    # Build prompt
    system_prompt = build_system_prompt(categories)

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable not set")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        reviews = json.load(f)

    to_classify = [r for r in reviews
                   if r.get("comment", "").strip()]
    no_comment = [r for r in reviews
                  if not r.get("comment", "").strip()]

    print(f"Categories: "
          f"{', '.join(name for name, _ in categories)} + Others")
    print(f"Reviews to classify: {len(to_classify)}")
    print(f"Reviews without comments (→ Others): {len(no_comment)}")

    for r in no_comment:
        r["category"] = ["Others"]

    batch_size = args.batch_size
    total_batches = ((len(to_classify) + batch_size - 1)
                     // batch_size)

    for i in range(0, len(to_classify), batch_size):
        batch = to_classify[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"Batch {batch_num}/{total_batches} "
              f"({len(batch)} reviews)...",
              end=" ", flush=True)

        result = classify_batch(token, batch, system_prompt)

        for r in batch:
            r["category"] = result.get(r["id"], ["Others"])

        matched = sum(1 for r in batch
                      if r["category"] != ["Others"])
        print(f"done ({matched} categorized)")

        if batch_num < total_batches:
            time.sleep(0.5)

    # Summary
    cat_counts: Counter = Counter()
    for r in reviews:
        for c in r.get("category", ["Others"]):
            cat_counts[c] += 1

    print(f"\n=== Classification Summary ===")
    for cat, count in cat_counts.most_common():
        print(f"  {cat}: {count}")
    print(f"  Total reviews: {len(reviews)}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {output_file}")


if __name__ == "__main__":
    main()
