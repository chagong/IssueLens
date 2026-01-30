#!/usr/bin/env python3
"""
Assign GitHub issues to specified assignees.

Usage:
    python assign_issue.py <owner> <repo> <issue_number> <assignees>

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


def assign_issue(
    owner: str, repo: str, issue_number: int, assignees: list[str], token: str
) -> dict:
    """Assign users to a GitHub issue."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/assignees"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = requests.post(url, headers=headers, json={"assignees": assignees})
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(
        description="Assign GitHub issues to specified assignees."
    )
    parser.add_argument("owner", help="Repository owner (e.g., 'microsoft')")
    parser.add_argument("repo", help="Repository name (e.g., 'vscode')")
    parser.add_argument("issue_number", type=int, help="Issue number to assign")
    parser.add_argument(
        "assignees", help="Comma-separated list of assignees (e.g., 'alice,bob')"
    )

    args = parser.parse_args()
    assignees = [a.strip().lstrip("@") for a in args.assignees.split(",")]

    try:
        token = get_github_token()
        result = assign_issue(
            args.owner, args.repo, args.issue_number, assignees, token
        )
        print(
            f"✅ Issue #{args.issue_number} assigned to: {', '.join('@' + a for a in assignees)}"
        )
        sys.exit(0)
    except ValueError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"❌ GitHub API error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
