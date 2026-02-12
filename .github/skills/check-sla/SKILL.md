---
name: check-sla
description: Check SLA (Service Level Agreement) status for GitHub issues. Use when (1) verifying issue SLA compliance, (2) checking if issues meet SLA requirements, (3) generating SLA status reports. Triggers on requests like "check SLA", "SLA status", "verify SLA compliance", "are issues meeting SLA".
---

# Check SLA Skill

Check SLA (Service Level Agreement) status for GitHub issues and generate a comprehensive status summary.

## Overview

This skill checks whether issues meet SLA requirements defined in the target repository's `.github/sla.md` file. If no SLA instructions are found, it uses the default SLA strategy. It generates a detailed SLA status summary for the checked issues.

## Workflow

1. **Input**: Receive issue URL or issue number with repository (owner/repo)
2. **Fetch SLA instructions**: Read `.github/sla.md` from the target repository
3. **Determine SLA criteria**: Use repository-specific rules or default strategy
4. **Fetch issue**: Get issue details (labels, parent links, status)
5. **Evaluate SLA**: Check if issue meets all SLA criteria
6. **Generate summary**: Produce a detailed SLA status report

## Required Input from User

1. **Issue**: Issue URL or issue number with repository (owner/repo)

## Reading SLA Instructions

Fetch `.github/sla.md` from the target repository using GitHub MCP tools.

If `.github/sla.md` exists, parse and apply its SLA criteria.

If `.github/sla.md` is not found, use the **Default SLA Strategy**.

## Default SLA Strategy

When no repository-specific SLA is defined, apply these criteria:

**An issue is SLA-compliant if ANY of these conditions are true:**
- Issue has "need more info" label
- Issue has "need log" label

**Otherwise, the issue MUST meet ALL of these conditions to be SLA-compliant:**
1. **Parent link exists**: Issue must have a parent issue linked (tracked-by or sub-issue relationship)
2. **No "need attention" label**: Issue must NOT have the "need attention" label

**Tolerance Period:**
- Issues have a **7-day grace period** from creation date before SLA violations are reported
- Issues open for ≤ 7 days that don't meet criteria are marked as **Warning** (not yet a violation)
- Issues open for > 7 days that don't meet criteria are marked as **Violation**

**SLA Status:**
- ✅ **Good**: Issue meets SLA criteria
- ⚠️ **Warning**: Issue does not meet SLA criteria but is within the 7-day tolerance period
- ❌ **Violation**: Issue does NOT meet SLA criteria and has exceeded the 7-day tolerance → Notify assignees

For detailed criteria documentation, see [references/default-sla.md](references/default-sla.md).

## Parent Link Detection

To check if an issue has a parent, use the GitHub sub-issues API or the reference script:

**API Endpoint:**
```
GET /repos/{owner}/{repo}/issues/{issue_number}/parent
```

**Using the reference script:**
```bash
python .github/skills/check-sla/scripts/get_parent_issue.py <owner> <repo> <issue_number>
```

The script requires `GITHUB_TOKEN` or `GH_TOKEN` environment variable. Exit codes:
- `0` — Parent found (JSON output on stdout)
- `2` — No parent issue found
- `1` — Error

**Fallback detection:** If the API returns 404 (no parent set via sub-issues), also check the issue body for links to the parent repository (e.g., `https://github.com/{owner}/{parent-repo}/issues/{number}`). If such a link exists, consider the issue as having a parent.

See [scripts/get_parent_issue.py](scripts/get_parent_issue.py) for implementation details.

## SLA Evaluation Logic

```
IF issue has label "need more info" OR "need log":
    SLA Status = GOOD (waiting on reporter)
ELSE:
    IF parent link exists AND "need attention" label NOT present:
        SLA Status = GOOD
    ELSE:
        days_open = (today - issue.created_at).days
        IF days_open <= tolerance_days (default 7):
            SLA Status = WARNING (within tolerance period)
        ELSE:
            SLA Status = VIOLATION
```

## Example Commands

- "Check SLA for issue #123 in microsoft/vscode"
- "Verify SLA status for https://github.com/owner/repo/issues/456"
- "Check if issue #789 meets SLA requirements"
- "Get SLA status report for issues #100, #101, #102 in owner/repo"

## Output

Generate a comprehensive SLA status summary:

**If SLA is Good:**
```
## ✅ SLA Status: Compliant

**Issue:** #123 - [Issue Title]
**Repository:** owner/repo
**Assignees:** @user1, @user2
**Status:** Compliant

### Evaluation Details
| Criteria | Status |
|----------|--------|
| Parent Link | ✅ Linked to #456 |
| "need attention" Label | ✅ Not present |
| Waiting Labels | N/A |

### Summary
This issue meets all SLA requirements. A parent tracking issue is linked and no immediate attention is required.
```

**If SLA is Warning (within 7-day tolerance):**
```
## ⚠️ SLA Status: Warning

**Issue:** #123 - [Issue Title]
**Repository:** owner/repo
**Assignees:** @user1, @user2
**Status:** Warning (within 7-day tolerance)
**Days Open:** 3 days (4 days remaining)

### Evaluation Details
| Criteria | Status |
|----------|--------|
| Parent Link | ❌ Missing |
| "need attention" Label | ✅ Not present |
| Waiting Labels | N/A |
| Tolerance Period | ⚠️ 3 of 7 days elapsed |

### Action Needed Before Deadline
- **Missing parent link**: Link this issue to a parent tracking issue within 4 days to avoid SLA violation
```

**If SLA is Violated (past 7-day tolerance):**
```
## ❌ SLA Status: Violation

**Issue:** #123 - [Issue Title]
**Repository:** owner/repo
**Assignees:** @user1, @user2
**Status:** Violation
**Days Open:** 10 days (exceeded 7-day tolerance by 3 days)

### Evaluation Details
| Criteria | Status |
|----------|--------|
| Parent Link | ❌ Missing |
| "need attention" Label | ❌ Present |
| Waiting Labels | N/A |
| Tolerance Period | ❌ Exceeded (10 days) |

### Failed Criteria
- **Missing parent link**: Issue is not linked to a parent tracking issue
- **Has "need attention" label**: Issue requires immediate attention

### Recommended Actions
1. Link this issue to a parent tracking issue
2. Address the "need attention" concerns and remove the label when resolved
```

**If Waiting on Reporter:**
```
## ⏸️ SLA Status: Waiting

**Issue:** #123 - [Issue Title]
**Repository:** owner/repo
**Assignees:** @user1, @user2
**Status:** Waiting on Reporter

### Evaluation Details
| Criteria | Status |
|----------|--------|
| Parent Link | ⏸️ Not evaluated |
| "need attention" Label | ⏸️ Not evaluated |
| Waiting Labels | ✅ "need more info" present |

### Summary
This issue is waiting for additional information from the reporter. SLA evaluation is paused until the reporter responds.
```
