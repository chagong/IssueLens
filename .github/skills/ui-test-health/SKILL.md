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
- Include the `failure_summary` block to give a one-glance view of the most impactful test failure

## Output Format

### 📊 UI Test Health — {timeFrame}

| Metric | Value |
|---|---|
| Time frame | {since} → {until} |
| PRs analyzed | {total_prs_analyzed} |
| Workflow runs fetched | {total_workflow_runs} |
| Overall pass rate (any attempt) | {pass_rate_any_attempt_pct}% |
| First-attempt pass rate | {first_attempt_pass_rate_pct}% |
| Workflow re-runs triggered | {total_retry_attempts} |
| Retry success rate | if `total_retry_attempts == 0`: `N/A — no re-runs triggered`; else: `{retry_success_rate_pct}%` |
| Retry distribution | if `total_retry_attempts == 0`: `N/A`; else: render each key present in `retry_distribution_pct` as `1 retry: {retry_distribution_pct["1"]}%, 2 retries: {retry_distribution_pct["2"]}%, 3+ retries: {retry_distribution_pct["3+"]}%` (omit keys with 0%) |
| Never-passed rate | {never_passed_rate_pct}% |

### 🔬 Per-Test-Class Breakdown

| IDE | Version | Test Class | First-Pass% | Any-Pass% | Flakiness |
|---|---|---|---|---|---|
| {ide_type} | {ide_version} | {test_class} | {first_attempt_pass_rate_pct}% | {any_attempt_pass_rate_pct}% | {flakiness_emoji} {flakiness_score} |

Flakiness emoji: 🟢 < 0.15 (stable) · 🟡 0.15–0.35 (moderate) · 🔴 > 0.35 (high)

### 🔁 Top Flaky Tests

_Only shown if `top_flaky_tests` is non-empty._

For each entry, show the retry breakdown from `retry_distribution`:
- `{ide_type} {ide_version} — {test_class}`: flakiness score **{flakiness_score}**, never passed **{never_passed}×**
  - Retry breakdown: 1 retry: {retry_distribution["1"]}×, 2 retries: {retry_distribution["2"]}×, 3+ retries: {retry_distribution["3+"]}×

### 🚨 PRs with Persistent Failures

_Only shown if `prs_with_persistent_failures` is non-empty._

For each PR:
> **PR #{pr_number}** [{pr_title}]({pr_url}) · @{pr_author}
> - ❌ `{ide_type} {ide_version} — {test_class}` failed on all {attempts} attempt(s) → [run]({latest_run_url})
>   - If `failed_cases` is a non-empty list, show each entry as a sub-bullet:
>     - `{test_case}`: `{exception_type}` — {exception_message}
>   - Omit the sub-bullets if `failed_cases` is null or empty

### 💥 Failure Summary

_Only shown if `failure_summary` is non-null._

**Worst offender:** `{ide_type} {ide_version} — {test_class}` ({never_passed_count} never-passed instance(s))

**Dominant failure:** `{dominant_exception_type}` ({occurrence_count} occurrence(s))

**Detail:** {dominant_exception_message}

### 🔍 Root Cause Analysis

_Only shown if `root_cause_analysis.categories` is non-empty._

Groups all failure instances by error pattern (not by test class) to reveal systemic issues.

**Summary table:**

| Category | Count | % | Top Sub-cause |
|---|---|---|---|
| {display_name} | {count} | {pct}% | {subcategories[0].label} |

**Error categories:**

| Category | What it matches | Typical root cause |
|---|---|---|
| `timeout` | `Exceeded timeout (PTxx)`, `Timeout(Xs)` | Backend connectivity, feature not loading, insufficient timeout |
| `component_not_found` | `Failed: Find UiComponent[xpath=...]` | UI refactoring changed class names/icons, plugin not loaded |
| `assertion_mismatch` | `Expected X but got Y`, `expected: <X> but was: <Y>` | Logic bugs, response format changes |
| `install_state` | `Expected button text to be 'Install'` | Plugin state issues |
| `other` | Unclassified errors | Various |

**Subcategory breakdown:** For each category with >1 subcategory, show:
- `{label}`: {count}x

For `timeout` subcategories, the label includes the failing function name extracted from the
`com.github.copilot` stack trace (e.g. `newSession (30S)`, `submitAndWaitForMessageSent (10S)`).

For `component_not_found` subcategories, the label includes the component type and identifying
attribute (e.g. `UiComponent[Copilot]`, `ActionButtonUi[coding_agent.svg]`).

### 📈 Health Assessment

Write a 3–5 sentence narrative covering:
- Overall health verdict: **Healthy** (pass rate >= 90%, never-passed rate < 5%) / **Marginal** / **Unhealthy**
- Which test class or IDE combo shows the most problems
- Root cause distribution: highlight the dominant error category and whether it suggests infrastructure (timeouts spread across many PRs), UI refactoring (component_not_found), or logic bugs (assertion_mismatch isolated to specific tests)
- Prioritized fix recommendations based on root cause categories (fix the highest-count category first)

---

For full JSON schema and field definitions, see [references/json-schema.md](references/json-schema.md).

## Notes

- Re-runs (run_attempt > 1) are detected automatically via the GitHub Actions API — no special setup required
- Job names are parsed dynamically using the pattern `UI Test ({ide_type}, {ide_version}, {test_class})`, so new matrix entries appear in reports automatically without script changes
- Runs with no associated PR (e.g. merge queue, orphaned re-runs) are counted in aggregate totals but omitted from per-PR breakdowns
- `cancelled` jobs count as failures for retry-pattern classification
- Error classification uses the `----Driver Error----` marker in test annotations to extract the human-readable error description, then categorizes by pattern matching
- The `stack_function` field for timeout errors is extracted from the first `com.github.copilot` frame in the stack trace, identifying which test step function timed out
- Failure annotations are fetched for both `never_passed` and `passed_after_retry` (first failed attempt) groups, giving root cause analysis coverage across all failure types
