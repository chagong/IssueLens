# JSON Schema Reference

## Full Schema

```json
{
  "type": "object",
  "required": ["metadata", "aggregate", "per_test_class", "per_pr", "top_flaky_tests", "prs_with_persistent_failures"],
  "properties": {
    "metadata": {
      "type": "object",
      "properties": {
        "owner":               { "type": "string" },
        "repo":                { "type": "string" },
        "workflow_name":       { "type": "string" },
        "since":               { "type": "string", "format": "date-time" },
        "until":               { "type": "string", "format": "date-time" },
        "days":                { "type": "integer" },
        "generated_at":        { "type": "string", "format": "date-time" },
        "total_workflow_runs": { "type": "integer" },
        "total_prs_analyzed":  { "type": "integer" }
      }
    },
    "aggregate": {
      "type": "object",
      "properties": {
        "total_pr_test_instances":     { "type": "integer" },
        "passed_first_attempt":        { "type": "integer" },
        "passed_after_retry":          { "type": "integer" },
        "never_passed":                { "type": "integer" },
        "in_progress":                 { "type": "integer" },
        "retry_distribution": {
          "type": "object",
          "description": "Histogram of retries needed to pass, summed across all test classes. Keys: '1', '2', '3+'. Counts of instances that needed that many retries.",
          "additionalProperties": { "type": "integer" }
        },
        "retry_distribution_pct": {
          "type": "object",
          "description": "Same as retry_distribution but as % of total passed_after_retry. Keys: '1', '2', '3+'. Only keys with count > 0 are included. Empty when passed_after_retry == 0.",
          "additionalProperties": { "type": "number" }
        },
        "pass_rate_any_attempt_pct":   { "type": "number",
          "description": "(passed_first + passed_after_retry) / total_resolved * 100" },
        "first_attempt_pass_rate_pct": { "type": "number",
          "description": "passed_first / total_resolved * 100" },
        "retry_success_rate_pct":      { "type": "number",
          "description": "passed_after_retry / (passed_after_retry + never_passed) * 100" },
        "never_passed_rate_pct":       { "type": "number",
          "description": "never_passed / total_resolved * 100" }
      }
    },
    "per_test_class": {
      "type": "array",
      "description": "One entry per unique (ide_type, ide_version, test_class) combination; sorted alphabetically",
      "items": {
        "type": "object",
        "properties": {
          "ide_type":                    { "type": "string", "description": "e.g. IC, PY, PS, WS" },
          "ide_version":                 { "type": "string", "description": "e.g. 2025.1, 2025.2" },
          "test_class":                  { "type": "string", "description": "e.g. CopilotChatTest, McpTest" },
          "total_instances":             { "type": "integer" },
          "passed_first_attempt":        { "type": "integer" },
          "passed_after_retry":          { "type": "integer" },
          "retry_distribution": {
            "type": "object",
            "description": "Histogram of how many retries were needed to pass. Keys: '1', '2', '3+'. Only present when passed_after_retry > 0.",
            "additionalProperties": { "type": "integer" }
          },
          "never_passed":                { "type": "integer" },
          "in_progress":                 { "type": "integer" },
          "first_attempt_pass_rate_pct": { "type": "number" },
          "any_attempt_pass_rate_pct":   { "type": "number" },
          "flakiness_score":             { "type": "number",
            "description": "passed_after_retry / total_resolved. Range 0.0–1.0." }
        }
      }
    },
    "per_pr": {
      "type": "array",
      "description": "One entry per unique head_sha; sorted has_failures > flaky_but_passing > all_green > in_progress",
      "items": {
        "type": "object",
        "properties": {
          "pr_number":            { "type": ["integer", "null"] },
          "pr_title":             { "type": "string" },
          "pr_url":               { "type": "string" },
          "pr_author":            { "type": "string" },
          "head_sha":             { "type": "string" },
          "total_test_instances": { "type": "integer" },
          "passed_first_attempt": { "type": "integer" },
          "passed_after_retry":   { "type": "integer" },
          "never_passed":         { "type": "integer" },
          "in_progress":          { "type": "integer" },
          "overall_status": {
            "type": "string",
            "enum": ["all_green", "flaky_but_passing", "has_failures", "in_progress"],
            "description": "all_green=zero retries+failures; flaky_but_passing=retries but no permanent failures; has_failures=≥1 never_passed; in_progress=runs still executing"
          },
          "test_results": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "ide_type":       { "type": "string" },
                "ide_version":    { "type": "string" },
                "test_class":     { "type": "string" },
                "status": {
                  "type": "string",
                  "enum": ["passed_first", "passed_after_retry", "never_passed", "in_progress"]
                },
                "attempts":       { "type": "integer" },
                "latest_run_url": { "type": "string" }
              }
            }
          }
        }
      }
    },
    "top_flaky_tests": {
      "type": "array",
      "description": "per_test_class entries with passed_after_retry >= 1; sorted by passed_after_retry desc",
      "items": {
        "type": "object",
        "properties": {
          "ide_type":           { "type": "string" },
          "ide_version":        { "type": "string" },
          "test_class":         { "type": "string" },
          "passed_after_retry": { "type": "integer" },
          "retry_distribution": {
            "type": "object",
            "description": "Histogram of retries needed to pass for this test class. Keys: '1', '2', '3+'.",
            "additionalProperties": { "type": "integer" }
          },
          "never_passed":       { "type": "integer" },
          "total_instances":    { "type": "integer" },
          "flakiness_score":    { "type": "number" }
        }
      }
    },
    "prs_with_persistent_failures": {
      "type": "array",
      "description": "PRs where at least one (ide_type, ide_version, test_class) never passed",
      "items": {
        "type": "object",
        "properties": {
          "pr_number":  { "type": "integer" },
          "pr_title":   { "type": "string" },
          "pr_url":     { "type": "string" },
          "pr_author":  { "type": "string" },
          "failed_tests": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "ide_type":       { "type": "string" },
                "ide_version":    { "type": "string" },
                "test_class":     { "type": "string" },
                "attempts":       { "type": "integer" },
                "latest_run_url": { "type": "string" },
                "failed_cases": {
                  "type": ["array", "null"],
                  "description": "Parsed failure cases from the CI job log. null=log unavailable, []=no FAILED blocks matched, [...]=one entry per FAILED block.",
                  "items": {
                    "type": "object",
                    "properties": {
                      "test_case":          { "type": "string", "description": "e.g. 'test copilot chat end to end'" },
                      "exception_type":     { "type": ["string", "null"], "description": "Specific inner exception type, e.g. 'WaitForConditionTimeoutException', 'ComponentLookupException'. Prefers specific types over generic 'AssertionFailedError'." },
                      "exception_message":  { "type": ["string", "null"], "description": "Human-readable error description from the ----Driver Error---- marker. E.g. 'Exceeded timeout (PT30S) for condition function' or 'Failed: Find UiComponent[...]'." },
                      "error_category":     { "type": "string", "enum": ["timeout", "component_not_found", "assertion_mismatch", "install_state", "other"], "description": "Classified error category for root cause analysis" },
                      "stack_function":     { "type": ["string", "null"], "description": "Topmost com.github.copilot function in the stack trace, e.g. 'newSession', 'submitAndWaitForMessageSent'. Useful for timeout diagnosis." }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  },
  "failure_summary": {
    "type": ["object", "null"],
    "description": "The worst (ide_type, ide_version, test_class) combo by never_passed count, plus its dominant exception across all failed cases. null if no never_passed entries exist.",
    "properties": {
      "worst_combo": {
        "type": "object",
        "properties": {
          "ide_type":           { "type": "string" },
          "ide_version":        { "type": "string" },
          "test_class":         { "type": "string" },
          "never_passed_count": { "type": "integer", "description": "Number of (sha, test_class) groups that never passed" }
        }
      },
      "dominant_exception_type":    { "type": ["string", "null"], "description": "Most frequent exception_type across all failed cases for the worst combo" },
      "dominant_exception_message": { "type": ["string", "null"], "description": "A representative message for the dominant exception type" },
      "occurrence_count":           { "type": "integer", "description": "How many FAILED cases had the dominant exception type" }
    }
  },
  "root_cause_analysis": {
    "type": "object",
    "description": "Groups all collected failure instances by error pattern for root cause diagnosis. Covers both never_passed and first-attempt failures from passed_after_retry groups.",
    "properties": {
      "total_failure_instances": { "type": "integer", "description": "Total number of individual failure cases analyzed" },
      "categories": {
        "type": "array",
        "description": "Failure categories sorted by count descending",
        "items": {
          "type": "object",
          "properties": {
            "category":     { "type": "string", "enum": ["timeout", "component_not_found", "assertion_mismatch", "install_state", "other"] },
            "display_name": { "type": "string", "description": "Human-readable category name" },
            "count":        { "type": "integer" },
            "pct":          { "type": "number", "description": "Percentage of total_failure_instances" },
            "subcategories": {
              "type": "array",
              "description": "Breakdown within the category. For timeout: by stack function. For component_not_found: by component. For assertion_mismatch: by assertion description.",
              "items": {
                "type": "object",
                "properties": {
                  "label":          { "type": "string", "description": "Sub-cause label, e.g. 'newSession (30S)' or 'UiComponent[Copilot]'" },
                  "count":          { "type": "integer" },
                  "sample_message": { "type": ["string", "null"], "description": "A representative error message for this sub-cause" }
                }
              }
            },
            "sample_errors": {
              "type": "array",
              "description": "Up to 5 unique error messages from this category",
              "items": { "type": "string" }
            }
          }
        }
      },
      "error_types": {
        "type": "array",
        "description": "Failure instances grouped by (test_case, error_category, normalized_key) with human-readable labels and affected run links. Sorted by count descending. Used by the notification to render concise top-error-type detail blocks.",
        "items": {
          "type": "object",
          "properties": {
            "label":          { "type": "string", "description": "Auto-generated human-readable label, e.g. 'Copilot Tab Not Found in Terminal Feature'" },
            "count":          { "type": "integer", "description": "Number of failure instances in this group" },
            "test_case":      { "type": "string", "description": "Original test method name, e.g. 'test terminal feature'" },
            "error_message":  { "type": ["string", "null"], "description": "Representative full error message (longest from the group, truncated to 200 chars)" },
            "error_category": { "type": "string", "enum": ["timeout", "component_not_found", "assertion_mismatch", "install_state", "other"] },
            "affected_runs":  {
              "type": "array",
              "description": "Deduplicated list of affected CI runs with suite info",
              "items": {
                "type": "object",
                "properties": {
                  "run_id":  { "type": "string", "description": "GitHub Actions run ID" },
                  "run_url": { "type": "string", "description": "Full URL to the workflow run" },
                  "suite":   { "type": "string", "description": "IDE type and version, e.g. 'IC_2025.2'" }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

## Field Guidelines

| Field | Description |
| ----- | ----------- |
| `flakiness_score` | `passed_after_retry / total_resolved`. 🟢 <0.15 stable, 🟡 0.15–0.35 moderate, 🔴 >0.35 high. |
| `retry_distribution` | Histogram of retries needed to pass. Keys `"1"`, `"2"`, `"3+"` — e.g. `{"1": 3, "2": 1, "3+": 2}` means 3 passed on 2nd attempt, 1 on 3rd, 2 needed 4+ attempts. |
| `retries_needed` | Per test-result entry: exact retries needed (0 = passed first, 1 = one retry, 2 = two retries, -1 = n/a). |
| `overall_status` | `all_green` = zero retries or failures; `flaky_but_passing` = retries happened but nothing permanently failed; `has_failures` = ≥1 never_passed; `in_progress` = runs still executing |
| `pass_rate_any_attempt_pct` | `(passed_first + passed_after_retry) / total_resolved × 100`. `total_resolved = total - in_progress` |
| `retry_success_rate_pct` | Of tests that required a retry, what % eventually passed |
| `top_flaky_tests` | Only entries with `passed_after_retry ≥ 1`; the flakiness candidates to investigate |
| `per_test_class` | Sorted alphabetically by `(ide_type, ide_version, test_class)` |
| `failed_cases` | Per `failed_tests` entry: list of parsed failure cases from the CI job log. `null` = log unavailable; `[]` = log fetched but no FAILED block matched; `[…]` = one dict per FAILED block with `test_case`, `exception_type`, `exception_message`, `error_category`, `stack_function`. |
| `error_category` | Classified root cause category. `timeout` = exceeded timeout / condition wait. `component_not_found` = UI element not found via xpath. `assertion_mismatch` = expected vs actual value mismatch. `install_state` = install button state wrong. `other` = unclassified. |
| `stack_function` | Topmost `com.github.copilot` function in the stack trace. Identifies which test step function caused a timeout (e.g. `newSession`, `submitAndWaitForMessageSent`, `verifyInlineCodeReviewComponentIsShowing`). `null` when no copilot stack frame found. |
| `failure_summary` | Top-level object identifying the worst `(ide_type, ide_version, test_class)` combo by `never_passed` count, with the dominant `exception_type` and a representative message across all its failed cases. `null` when there are no `never_passed` entries. |
| `root_cause_analysis` | Groups all failure instances by error pattern (not by test class). `categories` are sorted by count descending with subcategory breakdowns. `error_types` groups by (test_case, error_category, normalized_key) with human-readable labels and affected run links for notification rendering. Covers both `never_passed` and first-attempt failures from `passed_after_retry` groups. |
| `error_types` | Array within `root_cause_analysis`. Each entry represents a distinct error pattern grouped by test case and error type. Includes auto-generated label (e.g. "Copilot Tab Not Found in Terminal Feature"), occurrence count, representative error message, and deduplicated affected runs with suite info (`IC_2025.2`, `PY_2025.1`, etc.). Used by `build_notification_payload.py` to render concise top-3 error type detail blocks. |

## Example Output

```json
{
  "metadata": {
    "owner": "microsoft",
    "repo": "copilot-intellij",
    "workflow_name": "UI Test New",
    "since": "2026-02-27T00:00:00Z",
    "until": "2026-03-02T12:00:00Z",
    "days": 3,
    "generated_at": "2026-03-02T12:34:56Z",
    "total_workflow_runs": 47,
    "total_prs_analyzed": 8
  },
  "aggregate": {
    "total_pr_test_instances": 64,
    "passed_first_attempt": 48,
    "passed_after_retry": 9,
    "never_passed": 5,
    "in_progress": 2,
    "retry_distribution": { "1": 6, "2": 2, "3+": 1 },
    "retry_distribution_pct": { "1": 66.7, "2": 22.2, "3+": 11.1 },
    "pass_rate_any_attempt_pct": 91.9,
    "first_attempt_pass_rate_pct": 77.4,
    "retry_success_rate_pct": 64.3,
    "never_passed_rate_pct": 8.1
  },
  "per_test_class": [
    {
      "ide_type": "IC", "ide_version": "2025.2", "test_class": "CopilotChatTest",
      "total_instances": 8, "passed_first_attempt": 7, "passed_after_retry": 1,
      "never_passed": 0, "in_progress": 0,
      "first_attempt_pass_rate_pct": 87.5,
      "any_attempt_pass_rate_pct": 100.0,
      "flakiness_score": 0.125
    },
    {
      "ide_type": "IC", "ide_version": "2025.2", "test_class": "McpTest",
      "total_instances": 8, "passed_first_attempt": 5, "passed_after_retry": 2,
      "never_passed": 1, "in_progress": 0,
      "first_attempt_pass_rate_pct": 62.5,
      "any_attempt_pass_rate_pct": 87.5,
      "flakiness_score": 0.25
    },
    {
      "ide_type": "PY", "ide_version": "2025.1", "test_class": "CopilotChatTest",
      "total_instances": 8, "passed_first_attempt": 6, "passed_after_retry": 2,
      "never_passed": 0, "in_progress": 1,
      "first_attempt_pass_rate_pct": 75.0,
      "any_attempt_pass_rate_pct": 100.0,
      "flakiness_score": 0.25
    },
    {
      "ide_type": "PY", "ide_version": "2025.1", "test_class": "McpTest",
      "total_instances": 8, "passed_first_attempt": 5, "passed_after_retry": 1,
      "never_passed": 2, "in_progress": 0,
      "first_attempt_pass_rate_pct": 62.5,
      "any_attempt_pass_rate_pct": 75.0,
      "flakiness_score": 0.125
    }
  ],
  "per_pr": [
    {
      "pr_number": 4835,
      "pr_title": "fix: handle null response in chat completion",
      "pr_url": "https://github.com/microsoft/copilot-intellij/pull/4835",
      "pr_author": "devuser2",
      "head_sha": "b8e3d2f",
      "total_test_instances": 4,
      "passed_first_attempt": 2,
      "passed_after_retry": 0,
      "never_passed": 2,
      "in_progress": 0,
      "overall_status": "has_failures",
      "test_results": [
        {
          "ide_type": "IC", "ide_version": "2025.2", "test_class": "McpTest",
          "status": "never_passed", "attempts": 2,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210099"
        },
        {
          "ide_type": "PY", "ide_version": "2025.1", "test_class": "McpTest",
          "status": "never_passed", "attempts": 2,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210088"
        }
      ]
    },
    {
      "pr_number": 4821,
      "pr_title": "feat: add MCP tool selection UX",
      "pr_url": "https://github.com/microsoft/copilot-intellij/pull/4821",
      "pr_author": "devuser1",
      "head_sha": "a3f2c1d",
      "total_test_instances": 8,
      "passed_first_attempt": 7,
      "passed_after_retry": 1,
      "never_passed": 0,
      "in_progress": 0,
      "overall_status": "flaky_but_passing",
      "test_results": [
        {
          "ide_type": "IC", "ide_version": "2025.2", "test_class": "CopilotChatTest",
          "status": "passed_first", "attempts": 1,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14200001"
        },
        {
          "ide_type": "IC", "ide_version": "2025.2", "test_class": "McpTest",
          "status": "passed_after_retry", "attempts": 2,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14200045"
        },
        {
          "ide_type": "PY", "ide_version": "2025.1", "test_class": "CopilotChatTest",
          "status": "passed_first", "attempts": 1,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14200002"
        },
        {
          "ide_type": "PY", "ide_version": "2025.1", "test_class": "McpTest",
          "status": "passed_first", "attempts": 1,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14200003"
        }
      ]
    }
  ],
  "top_flaky_tests": [
    {
      "ide_type": "IC", "ide_version": "2025.2", "test_class": "McpTest",
      "passed_after_retry": 2, "retry_distribution": { "1": 1, "2": 1 },
      "never_passed": 1, "total_instances": 8,
      "flakiness_score": 0.25
    },
    {
      "ide_type": "PY", "ide_version": "2025.1", "test_class": "CopilotChatTest",
      "passed_after_retry": 2, "retry_distribution": { "1": 2 },
      "never_passed": 0, "total_instances": 8,
      "flakiness_score": 0.25
    }
  ],
  "prs_with_persistent_failures": [
    {
      "pr_number": 4835,
      "pr_title": "fix: handle null response in chat completion",
      "pr_url": "https://github.com/microsoft/copilot-intellij/pull/4835",
      "pr_author": "devuser2",
      "failed_tests": [
        {
          "ide_type": "IC", "ide_version": "2025.2", "test_class": "McpTest",
          "attempts": 2,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210099",
          "failed_cases": [
            {
              "test_case": "test mcp tool invocation",
              "exception_type": "WaitForConditionTimeoutException",
              "exception_message": "Exceeded timeout (PT30S) for condition function",
              "error_category": "timeout",
              "stack_function": "newSession"
            }
          ]
        },
        {
          "ide_type": "PY", "ide_version": "2025.1", "test_class": "McpTest",
          "attempts": 2,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210088",
          "failed_cases": null
        }
      ]
    }
  ],
  "failure_summary": {
    "worst_combo": {
      "ide_type": "PY",
      "ide_version": "2025.1",
      "test_class": "McpTest",
      "never_passed_count": 2
    },
    "dominant_exception_type": "WaitForConditionTimeoutException",
    "dominant_exception_message": "Exceeded timeout (PT30S) for condition function",
    "occurrence_count": 2
  },
  "root_cause_analysis": {
    "total_failure_instances": 12,
    "categories": [
      {
        "category": "timeout",
        "display_name": "Exceeded Timeout",
        "count": 5,
        "pct": 41.7,
        "subcategories": [
          { "label": "newSession (30S)", "count": 3, "sample_message": "Exceeded timeout (PT30S) for condition function" },
          { "label": "submitAndWaitForMessageSent (10S)", "count": 2, "sample_message": "Exceeded timeout (PT10S) for condition function" }
        ],
        "sample_errors": [
          "Exceeded timeout (PT30S) for condition function",
          "Exceeded timeout (PT10S) for condition function"
        ]
      },
      {
        "category": "component_not_found",
        "display_name": "UI Component Not Found",
        "count": 4,
        "pct": 33.3,
        "subcategories": [
          { "label": "UiComponent[Copilot]", "count": 3, "sample_message": "Timeout(5s): Failed: Find UiComponent[xpath=//div[@class='ContentTabLabel' and contains(@text, 'Copilot')]]" },
          { "label": "ActionButtonUi[coding_agent.svg]", "count": 1, "sample_message": "Timeout(15s): Failed: Find ActionButtonUi[xpath=//div[@myicon='coding_agent.svg']]" }
        ],
        "sample_errors": [
          "Timeout(5s): Failed: Find UiComponent[xpath=//div[@class='ContentTabLabel' and contains(@text, 'Copilot')]]",
          "Timeout(15s): Failed: Find ActionButtonUi[xpath=//div[@myicon='coding_agent.svg']]"
        ]
      },
      {
        "category": "assertion_mismatch",
        "display_name": "Assertion Mismatch",
        "count": 3,
        "pct": 25.0,
        "subcategories": [
          { "label": "Expected conflict hint in agent response, but got: Claude", "count": 3, "sample_message": "Expected conflict hint in agent response, but got: Claude Haiku 4.5..." }
        ],
        "sample_errors": [
          "Expected conflict hint in agent response, but got: Claude Haiku 4.5..."
        ]
      }
    ],
    "error_types": [
      {
        "label": "Copilot Not Found in Terminal Feature",
        "count": 3,
        "test_case": "test terminal feature",
        "error_message": "Timeout(5s): Failed: Find UiComponent[xpath=//div[@class='ContentTabLabel' and contains(@text, 'Copilot')]]",
        "error_category": "component_not_found",
        "affected_runs": [
          { "run_id": "14200001", "run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14200001", "suite": "IC_2025.2" },
          { "run_id": "14200045", "run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14200045", "suite": "PY_2025.1" }
        ]
      },
      {
        "label": "Assertion Mismatch in Copilot Chat End To End",
        "count": 3,
        "test_case": "test copilot chat end to end",
        "error_message": "Expected conflict hint in agent response, but got: Claude Haiku 4.5...",
        "error_category": "assertion_mismatch",
        "affected_runs": [
          { "run_id": "14210099", "run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210099", "suite": "IC_2025.2" },
          { "run_id": "14210088", "run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210088", "suite": "PY_2025.1" }
        ]
      },
      {
        "label": "newSession Timeout in Mcp Tool Invocation",
        "count": 2,
        "test_case": "test mcp tool invocation",
        "error_message": "Exceeded timeout (PT30S) for condition function",
        "error_category": "timeout",
        "affected_runs": [
          { "run_id": "14210099", "run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210099", "suite": "IC_2025.2" }
        ]
      }
    ]
  }
}
```
