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
                "latest_run_url": { "type": "string" }
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
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210099"
        },
        {
          "ide_type": "PY", "ide_version": "2025.1", "test_class": "McpTest",
          "attempts": 2,
          "latest_run_url": "https://github.com/microsoft/copilot-intellij/actions/runs/14210088"
        }
      ]
    }
  ]
}
```
