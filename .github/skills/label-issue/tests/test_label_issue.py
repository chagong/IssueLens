import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "label_issue.py"
SPEC = importlib.util.spec_from_file_location("label_issue", SCRIPT_PATH)
label_issue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(label_issue)


class AddLabelsTests(unittest.TestCase):
    def test_skips_post_when_all_labels_exist(self):
        get_response = Mock()
        get_response.json.return_value = [{"name": "Bug"}, {"name": "component: chat"}]

        with (
            patch.object(label_issue.requests, "get", return_value=get_response),
            patch.object(label_issue.requests, "post") as post,
        ):
            current_labels, added_labels = label_issue.add_labels(
                "owner", "repo", 123, ["bug", "component: chat"], "token"
            )

        self.assertEqual([{"name": "Bug"}, {"name": "component: chat"}], current_labels)
        self.assertEqual([], added_labels)
        post.assert_not_called()

    def test_posts_only_missing_labels(self):
        get_response = Mock()
        get_response.json.return_value = [{"name": "bug"}]
        post_response = Mock()
        post_response.json.return_value = [
            {"name": "bug"},
            {"name": "priority: high"},
        ]

        with (
            patch.object(label_issue.requests, "get", return_value=get_response),
            patch.object(label_issue.requests, "post", return_value=post_response) as post,
        ):
            _, added_labels = label_issue.add_labels(
                "owner", "repo", 123, ["bug", "priority: high"], "token"
            )

        self.assertEqual(["priority: high"], added_labels)
        post.assert_called_once_with(
            "https://api.github.com/repos/owner/repo/issues/123/labels",
            headers={
                "Authorization": "Bearer token",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"labels": ["priority: high"]},
        )


if __name__ == "__main__":
    unittest.main()
