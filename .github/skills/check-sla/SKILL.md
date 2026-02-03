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

**SLA Status:**
- ✅ **Good**: Issue meets SLA criteria
- ❌ **Violation**: Issue does NOT meet SLA criteria → Notify assignees

For detailed criteria documentation, see [references/default-sla.md](references/default-sla.md).

## SLA Evaluation Logic

```
IF issue has label "need more info" OR "need log":
    SLA Status = GOOD (waiting on reporter)
ELSE:
    IF parent link exists AND "need attention" label NOT present:
        SLA Status = GOOD
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

**If SLA is Violated:**
```
## ❌ SLA Status: Violation

**Issue:** #123 - [Issue Title]
**Repository:** owner/repo
**Assignees:** @user1, @user2
**Status:** Violation

### Evaluation Details
| Criteria | Status |
|----------|--------|
| Parent Link | ❌ Missing |
| "need attention" Label | ❌ Present |
| Waiting Labels | N/A |

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
