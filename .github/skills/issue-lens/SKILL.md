---
name: issue-lens
description: Triage GitHub issues and identify critical ones for repositories. Use when (1) analyzing issues for a time period, (2) identifying hot/blocking/regression issues, (3) generating daily/weekly issue reports, (4) filtering issues by severity criteria. Triggers on requests like "triage issues", "find critical issues", "daily issue report", "what issues need attention".
---

# GitHub Issue Lens

Triage GitHub issues and identify critical ones based on user impact and severity.

## Workflow

1. Determine time scope from user input (default: today)
2. Retrieve issues opened within the time scope
3. Apply critical issue criteria to filter
4. Generate JSON summary

## Critical Issue Criteria

### Hot Issues
- 2+ similar issues from different users (same symptom/error pattern)
- 2+ user reactions (👍) or comments
- 3+ non-bot comments (exclude "github-action" automation)

### Blocking Issues
- Core product function broken with no workaround

### Regression Issues
- Previously working feature broken in current release

## Output Format

Generate JSON with these fields:
- `title`: Report title
- `timeFrame`: Date range covered
- `totalIssues`: Count of all issues
- `criticalIssues`: Count of critical issues
- `overallSummary`: Brief overview (no repo names)
- `criticalIssuesSummary[]`: Array with issueNumber, url, title, summary, labels
- `allIssues[]`: Array with issueNumber, url, title
- `workflowRunUrl`: Current workflow run URL

For full schema and examples, see [references/json-schema.md](references/json-schema.md).

## Labels Format

In `labels` property, use: `🔴 **High Priority** | 🏷️ label1, label2`

Priority levels: High (🔴), Medium (🟡), Low (🟢)
