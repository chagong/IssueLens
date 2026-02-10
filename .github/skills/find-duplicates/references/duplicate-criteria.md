# Duplicate Detection Criteria Reference

This document provides detailed examples for each duplicate detection criterion.

## Table of Contents

1. [Primary Match Criteria](#primary-match-criteria)
2. [Supporting Evidence Criteria](#supporting-evidence-criteria)
3. [Edge Cases](#edge-cases)
4. [Anti-Patterns (Not Duplicates)](#anti-patterns-not-duplicates)

---

## Primary Match Criteria

At least ONE primary criterion must match to consider issues as potential duplicates.

### 1. Identical Error Message

**What to look for:**
- Exact error codes (e.g., `E0001`, `ECONNREFUSED`)
- Exception types with class names (e.g., `java.lang.NullPointerException`)
- Error message text (e.g., "Cannot read property 'x' of undefined")

**Examples of matches:**

```
Issue A: "Getting error: ENOENT: no such file or directory, open '/tmp/cache.json'"
Issue B: "Error: ENOENT: no such file or directory, open '/tmp/cache.json'"
→ MATCH: Same error code and path
```

```
Issue A: "TypeError: Cannot read property 'map' of undefined"
Issue B: "TypeError: Cannot read property 'map' of undefined at Component.render"
→ MATCH: Same error type and property
```

**Not a match:**

```
Issue A: "Connection timeout after 30s"
Issue B: "Request timeout - no response received"
→ NO MATCH: Similar concept but different error messages
```

### 2. Same Stack Trace Signature

**What to look for:**
- Top 3 function calls in the stack match
- Ignore line numbers (they change between versions)
- Focus on method/function names and file names

**Example of match:**

```
Issue A:
  at Parser.parse (parser.js:42)
  at Compiler.compile (compiler.js:128)
  at build (index.js:15)

Issue B:
  at Parser.parse (parser.js:45)
  at Compiler.compile (compiler.js:130)
  at build (index.js:18)
→ MATCH: Same call chain, different line numbers
```

### 3. Identical Reproduction Steps

**What to look for:**
- Same sequence of actions
- Same input values/files
- Same configuration state

**Example of match:**

```
Issue A:
1. Open a large project (>1000 files)
2. Search for "TODO"
3. Click on first result
4. App freezes

Issue B:
1. Load project with many files
2. Use search feature
3. Select a search result
4. UI becomes unresponsive
→ MATCH: Same steps, slightly different wording
```

---

## Supporting Evidence Criteria

At least TWO supporting criteria must match (in addition to a primary match).

### 1. Same Component/Area

**Indicators:**
- Matching area labels (e.g., `area:editor`, `component:search`)
- Same file paths mentioned
- Same feature names referenced

### 2. Same Environment

**Indicators:**
- Operating system and version
- Runtime version (Node.js, Java, Python, etc.)
- Browser and version
- Hardware specifics (if relevant)

### 3. Same Symptom Description

**Indicators:**
- UI behavior (freeze, crash, flicker)
- Performance issues (slow, memory leak)
- Data issues (corruption, loss, incorrect)

### 4. Same Trigger Condition

**Indicators:**
- Specific input size or type
- Specific configuration
- Specific timing or sequence
- Specific user permissions

### 5. Cross-Referenced

**Indicators:**
- Comment mentions "duplicate of #X"
- Body links to another issue
- User says "I have the same problem as #X"

---

## Edge Cases

### Generic Errors Need Extra Evidence

These common errors require STRONG supporting evidence:

- "Connection refused" / "Connection timeout"
- "Permission denied"
- "Out of memory"
- "File not found"
- "Invalid argument"
- "Unexpected token"

**Rule:** For generic errors, require 3+ supporting evidence matches.

### Different Versions of Same Bug

Issues may describe the same root cause but:
- Different stack traces (code changed)
- Different error messages (error handling changed)
- Different symptoms (different code paths)

**Rule:** Consider as related, not duplicate. Link them but keep both open.

### Same Root Cause, Different Manifestations

```
Issue A: "App crashes when opening settings"
Issue B: "App crashes when changing theme"
```

Both caused by same null pointer bug, but different triggers.

**Rule:** These are related issues, potentially same root cause, but NOT duplicates. Different users will search for different symptoms.

---

## Anti-Patterns (Not Duplicates)

### Same Feature, Different Problem

```
Issue A: "Search is slow"
Issue B: "Search returns wrong results"
→ NOT DUPLICATE: Same feature, different issues
```

### Same Error Type, Different Cause

```
Issue A: "NullPointerException in UserService.getUser()"
Issue B: "NullPointerException in OrderService.getOrder()"
→ NOT DUPLICATE: Same exception type, different locations
```

### Vague Similarity

```
Issue A: "App doesn't work"
Issue B: "Something is broken"
→ NOT DUPLICATE: Too vague to determine
```

### Same Workaround Needed

```
Issue A: "Feature X broken, workaround is to restart"
Issue B: "Feature Y broken, workaround is to restart"
→ NOT DUPLICATE: Same workaround doesn't mean same bug
```
