---
name: assign-issue
description: Assign GitHub issues to the right person based on technical area ownership and historical patterns. Use when (1) auto-assigning new issues, (2) finding the right owner for an issue, (3) routing issues to area experts. Triggers on requests like "assign issue", "find owner for issue", "who should handle this issue", "route this issue".
---

# Assign Issue Skill

Automatically assign GitHub issues to the appropriate owner based on technical area mapping and historical assignment patterns.

## Overview

This skill determines the best assignee for a GitHub issue using two complementary strategies:
1. **Static Mapping**: Match issue to technical areas defined in `area_owners.md`
2. **Historical Patterns**: Query similar issues to find frequently assigned owners

## Assignment Strategies

### Strategy 1: Static Area Mapping

Read the repository's `area_owners.md` file (typically in `.github/` or root) to get technical area definitions and their owners.

**Expected format of `area_owners.md`:**
```markdown
# Area Owners

## Debugging
- **Keywords**: debugger, breakpoint, launch.json, debug console, step through
- **Paths**: src/debugger/**, extension/debug/**
- **Owners**: @debugger-team, @alice

## Language Server
- **Keywords**: IntelliSense, completion, hover, go to definition, LSP
- **Paths**: src/languageserver/**, src/lsp/**
- **Owners**: @lsp-team, @bob

## Build & Compile
- **Keywords**: build, compile, maven, gradle, ant, classpath
- **Paths**: src/build/**, src/compiler/**
- **Owners**: @build-team, @charlie
```

**Matching algorithm:**
1. Extract issue title, body, and labels
2. Match against area keywords (case-insensitive)
3. If file paths are mentioned, match against area paths
4. Return owners from the best matching area

### Strategy 2: Similar Issues Query

Query the repository for similar closed/resolved issues and analyze assignment patterns.

**Process:**
1. Use GitHub search to find similar issues:
   - Search by key terms from issue title
   - Filter to closed/resolved issues
   - Limit to recent issues (last 6-12 months)
2. Collect assignees from top 10-20 similar issues
3. Rank by frequency of assignment
4. Return the most frequently assigned person

## Workflow

1. **Input**: Receive issue number and repository (owner/repo)
2. **Fetch issue**: Get issue details (title, body, labels)
3. **Strategy 1 - Area Mapping**:
   - Read `area_owners.md` from the repository
   - Match issue content to technical areas
   - Get candidate owners from matching areas
4. **Strategy 2 - Similar Issues**:
   - Search for similar closed issues
   - Analyze assignee patterns
   - Get candidate owners by frequency
5. **Combine Results**:
   - If both strategies agree → high confidence assignment
   - If only area mapping matches → use area owner
   - If only similar issues match → use historical pattern
   - If neither matches → report no confident match
6. **Assign Issue**: Use GitHub API to assign the selected owner
7. **Report**: Confirm assignment with reasoning

## Assigning Issues

Once the best assignee is determined, run the bundled Python script to assign the issue:

```bash
# Install dependency
pip install requests

# Assign an issue to one or more users
python scripts/assign_issue.py <owner> <repo> <issue_number> <assignees>

# Example: assign issue #123 to alice
python scripts/assign_issue.py microsoft vscode 123 alice

# Example: assign to multiple users
python scripts/assign_issue.py microsoft vscode 123 alice,bob
```

The script [scripts/assign_issue.py](scripts/assign_issue.py) handles the GitHub API call to assign issues.

## Example Commands

- "Assign issue #123 to the right person"
- "Who should handle microsoft/vscode-java#456?"
- "Find the owner for this debugging issue"
- "Route issue #789 to the appropriate team"

## Output

Report the assignment decision with:
- **Assigned to**: @username
- **Confidence**: High/Medium/Low
- **Reasoning**: 
  - Area match: "Matched 'Debugging' area (keywords: debugger, breakpoint)"
  - Similar issues: "5 of 8 similar issues were assigned to @alice"
- **Action taken**: Issue assigned / Assignment suggested (if no write permission)

## Example Output

```
✅ Issue #123 assigned to @alice

**Confidence:** High

**Reasoning:**
- Area mapping: Matched "Debugging" area (keywords: breakpoint, debug console)
- Similar issues: @alice was assigned 6 of 10 similar debugging issues

**Similar issues analyzed:**
- #100: Debug breakpoints not working → @alice
- #95: Debug console output missing → @alice
- #88: Launch.json validation error → @bob
```

## Fallback Behavior

If no confident match is found:
1. List candidate owners with their match scores
2. Suggest manual review

## Configuration

The skill looks for `area_owners.md` in these locations (in order):
1. `.github/area_owners.md`
2. `docs/area_owners.md`
3. `area_owners.md` (root)

If not found, the skill falls back to similar issues strategy only.