---
name: find-duplicates
description: Find duplicate GitHub issues by comparing a given issue against existing issues in the repository. Use when (1) checking if a new issue is a duplicate, (2) finding related/similar issues, (3) detecting duplicate reports before triaging. Triggers on requests like "find duplicates", "is this a duplicate", "check for duplicates", "find similar issues".
---

# Find Duplicates Skill

Identify potential duplicate issues by analyzing semantic similarity, error patterns, and affected components.

## Workflow

1. **Input**: Receive issue URL or issue number with repository (owner/repo)
2. **Fetch target issue**: Get issue details (title, body, labels)
3. **Fetch candidate issues**: List recent issues (both open and closed) in the repository
4. **Compare issues**: Apply duplicate detection criteria
5. **Report**: Output potential duplicates with confidence scores

## Duplicate Detection Criteria

Apply a **high bar** for duplicate detection - only flag issues as duplicates when there is strong evidence. False positives are costly (wastes time, frustrates reporters).

### Required: Primary Match (at least ONE must match)

1. **Identical Error Message**
   - Same error code, exception type, or stack trace pattern
   - Example: Both issues contain "NullPointerException at com.example.Service.process()"

2. **Same Stack Trace Signature**
   - Top 3 frames of stack trace match (ignoring line numbers)
   - Example: Both show crash in `Parser.parse() -> Lexer.tokenize() -> Reader.read()`

3. **Identical Reproduction Steps**
   - Same sequence of user actions leads to the problem
   - Example: Both describe "click File -> Export -> PDF -> crashes"

### Required: Supporting Evidence (at least TWO must match)

1. **Same Component/Area**
   - Issues affect the same feature, module, or component
   - Match based on: labels (area:*, component:*), file paths mentioned, feature names

2. **Same Environment**
   - Same OS, version, runtime, or platform
   - Example: Both report issue on "Windows 11 + Java 17"

3. **Same Symptom Description**
   - Similar user-reported behavior (beyond just error messages)
   - Example: Both describe "UI freezes when loading large files"

4. **Same Trigger Condition**
   - Same input, configuration, or scenario causes the issue
   - Example: Both triggered by "files larger than 100MB"

5. **Cross-Referenced**
   - Users explicitly mention the other issue
   - Comments link to or reference the other issue

## Confidence Scoring

Rate each potential duplicate:

| Confidence | Criteria Met |
|------------|--------------|
| **High (90%+)** | 1 Primary + 3+ Supporting, or explicit cross-reference |
| **Medium (70-89%)** | 1 Primary + 2 Supporting |
| **Low (50-69%)** | 1 Primary + 1 Supporting (flag for manual review) |
| **Not Duplicate** | No Primary match, or insufficient Supporting evidence |

**Only report High and Medium confidence matches.** Low confidence matches should only be mentioned as "possibly related".

## Issue Comparison Process

### Step 1: Extract Key Signals from Target Issue

Parse the target issue for:
- Error messages/codes (regex for exceptions, error codes)
- Stack traces (multi-line code blocks with function calls)
- File paths and line numbers
- Component names (from labels or body text)
- Environment info (OS, version, runtime)
- Reproduction steps (numbered lists, "steps to reproduce")
- Affected feature/area

### Step 2: Fetch Candidate Issues

Search for candidates using GitHub API:
```
# Search both open and closed issues in same repo, last 90 days
github-mcp-server-list_issues owner=<owner> repo=<repo>
```

**Important:** Include both open AND closed issues as candidates. A new issue may be a duplicate of an already-fixed issue, which helps:
- Avoid redundant investigation
- Point reporters to existing solutions
- Track recurring problems

Filter candidates by:
- Same labels (especially area/component labels)
- Similar keywords in title
- Created within last 90 days (configurable)

### Step 3: Compare Each Candidate

For each candidate issue:
1. Check Primary Match criteria
2. If Primary matches, check Supporting Evidence
3. Calculate confidence score
4. Record matching evidence

For detailed examples of each criterion, see [references/duplicate-criteria.md](references/duplicate-criteria.md).

## Output Format

```json
{
  "targetIssue": {
    "number": 123,
    "url": "https://github.com/owner/repo/issues/123",
    "title": "App crashes when exporting PDF"
  },
  "duplicatesFound": 1,
  "potentialDuplicates": [
    {
      "number": 98,
      "url": "https://github.com/owner/repo/issues/98",
      "title": "PDF export causes crash on large documents",
      "confidence": "High",
      "confidenceScore": 92,
      "primaryMatch": "Identical error: NullPointerException at PdfExporter.export()",
      "supportingEvidence": [
        "Same component: PDF Export (label: area:export)",
        "Same trigger: Files larger than 50MB",
        "Same environment: Windows 11"
      ],
      "recommendation": "Close #123 as duplicate of #98"
    }
  ],
  "possiblyRelated": [
    {
      "number": 87,
      "url": "https://github.com/owner/repo/issues/87",
      "title": "Export feature slow on large files",
      "reason": "Same component but different symptom (performance vs crash)"
    }
  ]
}
```

## Example Commands

- "Find duplicates for issue #123 in microsoft/vscode"
- "Is this issue a duplicate? https://github.com/owner/repo/issues/456"
- "Check for similar issues to #789"
- "Find related issues for this bug report"

## Example Output

```
## Duplicate Check for Issue #123

**Target Issue:** App crashes when exporting PDF
**Candidates Analyzed:** 47 issues (open and closed)

### Potential Duplicate Found (High Confidence: 92%)

**Issue #98:** PDF export causes crash on large documents
https://github.com/owner/repo/issues/98

**Primary Match:**
- Identical error: `NullPointerException at PdfExporter.export()`

**Supporting Evidence:**
- Same component: PDF Export (label: area:export)
- Same trigger: Files larger than 50MB  
- Same environment: Windows 11

**Recommendation:** Close #123 as duplicate of #98

---

### Possibly Related (Not Duplicate)

**Issue #87:** Export feature slow on large files
- Same component but different symptom (performance vs crash)
```

## Guidelines for Accurate Detection

### Avoid False Positives

- Generic errors ("connection failed", "timeout") need additional evidence
- Same feature area alone is NOT sufficient
- Similar titles without matching technical details are NOT duplicates

### When to Flag for Manual Review

- Error messages are similar but not identical
- Different environments but same symptoms
- One issue lacks technical details to compare

## Configuration

The skill uses GitHub MCP tools. No additional configuration required.