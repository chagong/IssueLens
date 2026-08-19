#!/usr/bin/env python3
"""
Add labels to GitHub issues.

Usage:
    python label_issue.py <owner> <repo> <issue_number> <labels>

Environment Variables:
    GITHUB_ACCESS_TOKEN or GITHUB_PAT: GitHub personal access token with repo scope
"""

import os
import sys
import argparse
import requests


def get_github_token() -> str:
    """Get GitHub token from environment variables."""
    token = os.environ.get("GITHUB_ACCESS_TOKEN") or os.environ.get("GITHUB_PAT")
    if not token:
        raise ValueError(
            "GitHub token not found. Set GITHUB_ACCESS_TOKEN or GITHUB_PAT environment variable."
        )
    return token


def add_labels(
    owner: str, repo: str, issue_number: int, labels: list[str], token: str
) -> tuple[list[dict], list[str]]:
    """Add only labels that are not already on a GitHub issue."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    current_labels = response.json()
    current_names = {label["name"].casefold() for label in current_labels}
    new_labels = [label for label in labels if label.casefold() not in current_names]

    if not new_labels:
        return current_labels, []

    response = requests.post(url, headers=headers, json={"labels": new_labels})
    response.raise_for_status()
    return response.json(), new_labels


def main():
    parser = argparse.ArgumentParser(
        description="Add labels to GitHub issues."
    )
    parser.add_argument("owner", help="Repository owner (e.g., 'microsoft')")
    parser.add_argument("repo", help="Repository name (e.g., 'vscode')")
    parser.add_argument("issue_number", type=int, help="Issue number to label")
    parser.add_argument(
        "labels", help="Comma-separated list of labels (e.g., 'bug,priority:high')"
    )

    args = parser.parse_args()
    labels = [label.strip() for label in args.labels.split(",") if label.strip()]

    if not labels:
        print("❌ No labels provided.", file=sys.stderr)
        sys.exit(1)

    try:
        token = get_github_token()
        _, added_labels = add_labels(
            args.owner, args.repo, args.issue_number, labels, token
        )
        if added_labels:
            print(
                f"✅ Labels added to issue #{args.issue_number}: "
                f"{', '.join(added_labels)}"
            )
        else:
            print(f"✅ Issue #{args.issue_number} already has all requested labels; no changes made.")
        sys.exit(0)
    except ValueError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"❌ GitHub API error: {e}", file=sys.stderr)
        if e.response is not None:
            print(f"   Response: {e.response.text}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
