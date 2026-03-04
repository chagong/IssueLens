---
name: ui-test-health
description: Analyze UI test health for the microsoft/copilot-intellij repository. Use when (1) checking UI test pass/fail rates over a time period, (2) identifying flaky or unstable tests that fail intermittently, (3) reviewing which PRs have persistent test failures, (4) monitoring CI health trends for the UI Test New workflow. Triggers on requests like "UI test health", "check UI test results", "which tests are flaky", "UI test failures in the last 3 days", "are UI tests stable", "CI health report", "show me flaky UI tests", "unstable test cases".
---

# UI Test Health Skill

Analyze UI test pass/fail rates, flakiness patterns, and persistent failures for the `UI Test New` workflow in `microsoft/copilot-intellij`.

## Workflow

### Step 1 — Determine Time Scope

Parse user input (default: last 3 days):

| User input | `--days` value |
|---|---|
| "today" or "last 24 hours" | `1` |
| "last 3 days" or no scope | `3` (default) |
| "last week" or "past 7 days" | `7` |
| "last N days" | `N` |

### Step 2 — Run the Fetch Script

```bash
py .github/skills/ui-test-health/scripts/fetch_ui_test_runs.py \
  --owner microsoft \
  --repo copilot-intellij \
  --days {N} \
  --workflow-name "UI Test New" \
  --output {workspace}/output/ui_test_health.json
```

Requires `GITHUB_TOKEN` (or `GH_TOKEN`) with `repo` and `actions:read` scopes.

Read the resulting JSON from the output path.

### Step 3 — Render the Health Report

Format the report as markdown using the sections below.

### Step 4 — Highlight Actionable Items

Always surface at the end of the report:
- Tests with `never_passed > 0` → **blocking** — require investigation before merging
- Tests with `flakiness_score > 0.15` → **unstable** — candidates for stabilization
- All entries in `prs_with_persistent_failures` → PR authors need to be notified

## Output Format

### 📊 UI Test Health — {timeFrame}

| Key | Value |
|---|---|
| PRs analyzed | {total_prs_analyzed} |
| Workflow runs | {total_workflow_runs} |
| Pass rate (any attempt) | {pass_rate_any_attempt_pct}% |
| Pass rate (first attempt) | {first_attempt_pass_rate_pct}% |
| Re-runs | {total_retry_attempts} |
| Retry success rate | if `total_retry_attempts == 0`: `N/A`; else: `{retry_success_rate_pct}%` |
| Never-passed rate | {never_passed_rate_pct}% |

### ⚠️ Worst Flaky Test

_Only shown if `worst_flaky_test_case` is non-null._

```
⚠️ Worst: `{ide_type} {ide_version} — {test_class}.{test_case}` | flakiness: {flakiness_score} | never-passed: {never_passed}× — [latest run]({latest_run_url})
```

If `failure_message` is non-empty, immediately follow with a fenced code block:

````
### 🔍 Worst Test Failure

```
{failure_message}
```
````

### 🔬 Per-Test-Case Breakdown

| IDE | Version | Test Class | Test Case | First-Pass% | Any-Pass% | Flakiness |
|---|---|---|---|---|---|---|
| {ide_type} | {ide_version} | {test_class} | {test_case} | {first_attempt_pass_rate_pct}% | {any_attempt_pass_rate_pct}% | {flakiness_emoji} {flakiness_score} |

Rows are sorted by worst flakiness first within each class. Failure messages are extracted from CI job logs using the Gradle `TestClass > testCase() FAILED` pattern; falls back to job-level conclusion if no log data is found.

Flakiness emoji: 🟢 < 0.15 (stable) · 🟡 0.15–0.35 (moderate) · 🔴 > 0.35 (high)

### 🔍 Failure Summary

_Only shown if any `per_test_case` entry has a non-empty `failure_message`._

Groups failures by category (first match wins):
- **🔎 Element Not Found** — message contains: `waitForException`, `elementNotFound`, `element not found`, `NoSuchElementException`, `unable to find element`
- **❌ Assertion Failures** — message contains: `AssertionError`, `expected:`, `but was:`, `AssertionFailedError`, or starts with `assert`
- **⏱️ Timeouts** — message contains: `timeout`, `timed out`, `timedOut`
- **⚙️ Other Failures** — everything else

For each category: lists up to 3 distinct (deduplicated) failure messages with the affected test case name(s) and PR count.

Ends with a `**PRs with persistent failures:**` link list (up to 5 PRs, newest first).

### 💥 Failure Messages

_Only shown if any failing test case has a non-empty `failure_message`._

For each failing test case (sorted by `never_passed` desc, then `flakiness_score` desc), show:

```
`{ide_type} {ide_version} — {test_class}.{test_case}` · [run]({latest_run_url})
```
{failure_message} (in a fenced code block, truncated to 400 chars)

### 🚨 PRs with Persistent Failures

_Only shown if `prs_with_persistent_failures` is non-empty._

For each PR:
> PR #{pr_number} [{pr_title}]({pr_url}) · @{pr_author}
> - ❌ `{ide_type} {ide_version} — {test_class}` failed on all {attempts} attempt(s) → [run]({latest_run_url})

### 📈 Health Assessment

Write a 3–5 sentence narrative covering:
- Overall health verdict: Healthy (pass rate ≥ 90%, never-passed rate < 5%) / Marginal / Unhealthy
- Which test class or IDE combo shows the most problems
- Whether failures look infrastructure-related (broad failures across many PRs) vs code-related (failures isolated to specific PRs/test classes)
- Recommended next action (if any)

---

For full JSON schema and field definitions, see [references/json-schema.md](references/json-schema.md).

## Notes

- Re-runs (run_attempt > 1) are detected automatically via the GitHub Actions API — no special setup required
- Job names are parsed dynamically using the pattern `UI Test ({ide_type}, {ide_version}, {test_class})`, so new matrix entries appear in reports automatically without script changes
- Runs with no associated PR (e.g. merge queue, orphaned re-runs) are counted in aggregate totals but omitted from per-PR breakdowns
- `cancelled` jobs count as failures for retry-pattern classification
