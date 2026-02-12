"""Get the parent issue for a GitHub issue using the sub-issues API.

Usage:
    python get_parent_issue.py <owner> <repo> <issue_number>

Environment variables:
    GITHUB_TOKEN or GH_TOKEN - GitHub personal access token

Exit codes:
    0 - Parent found (prints JSON to stdout)
    1 - Error (prints message to stderr)
    2 - No parent issue found
"""

import argparse
import json
import os
import sys

import requests


def get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError(
            "GitHub token not found. Set GITHUB_TOKEN or GH_TOKEN environment variable."
        )
    return token


def get_parent_issue(owner: str, repo: str, issue_number: int, token: str) -> dict | None:
    """Fetch the parent issue via GET /repos/{owner}/{repo}/issues/{issue_number}/parent."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/parent"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    if response.status_code == 404:
        return None

    response.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Get the parent issue for a GitHub issue."
    )
    parser.add_argument("owner", help="Repository owner (e.g. 'microsoft')")
    parser.add_argument("repo", help="Repository name (e.g. 'copilot-intellij-feedback')")
    parser.add_argument("issue_number", type=int, help="Issue number")
    args = parser.parse_args()

    try:
        token = get_github_token()
        parent = get_parent_issue(args.owner, args.repo, args.issue_number, token)

        if parent is None:
            print(
                f"❌ No parent issue found for {args.owner}/{args.repo}#{args.issue_number}",
                file=sys.stderr,
            )
            sys.exit(2)

        result = {
            "issue": f"{args.owner}/{args.repo}#{args.issue_number}",
            "parent_number": parent["number"],
            "parent_url": parent["html_url"],
            "parent_title": parent["title"],
            "parent_repo": parent.get("repository", {}).get("full_name", ""),
            "parent_state": parent["state"],
        }

        print(json.dumps(result, indent=2))
        print(
            f"\n✅ Parent found: {result['parent_repo']}#{result['parent_number']} - {result['parent_title']}",
            file=sys.stderr,
        )

    except ValueError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"❌ API error: {e}", file=sys.stderr)
        if e.response is not None:
            print(f"   Response: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
