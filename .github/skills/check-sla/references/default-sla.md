# Default SLA Strategy

This document defines the default SLA criteria when no repository-specific `.github/sla.md` is found.

## SLA Criteria

### Exempt Statuses (SLA automatically Good)

Issues with these labels are exempt from SLA checks because they are waiting on external input:

| Label | Description |
|-------|-------------|
| `needs more info` | Waiting for reporter to provide additional information |
| `needs log` | Waiting for reporter to provide logs or diagnostic data |

### Required Conditions (for non-exempt issues)

For issues that are not exempt, **all** of these conditions must be met:

| Condition | Requirement | Rationale |
|-----------|-------------|-----------|
| Parent link | Must exist | Ensures issue is tracked in a larger work item or epic |
| No "need attention" label | Must NOT have this label | This label indicates the issue requires immediate action |

## Evaluation Flow

```
┌─────────────────────────────────────┐
│ Start: Evaluate Issue SLA           │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ Has "needs more info" or "needs log"? │
└─────────────────┬───────────────────┘
                  │
         ┌───────┴───────┐
         │ YES           │ NO
         ▼               ▼
┌─────────────┐  ┌─────────────────────┐
│ SLA: GOOD   │  │ Check parent link   │
│ (Exempt)    │  │ and "needs attention"│
└─────────────┘  └─────────┬───────────┘
                           │
                  ┌────────┴────────┐
                  │                 │
         Parent exists AND     Otherwise
         no "needs attention"
                  │                 │
                  ▼                 ▼
           ┌───────────┐    ┌─────────────┐
           │ SLA: GOOD │    │ SLA: VIOLATION│
           └───────────┘    └─────────────┘
```

## Label Matching

Labels should be matched case-insensitively. The following variations within each group are **identical** and must be treated as the same label:

- **"need more info"** group: `need more info`, `needs more info`, `need-more-info`, `needs-more-info`
- **"need log"** group: `need log`, `needs log`, `need-log`, `needs-log`
- **"need attention"** group: `need attention`, `needs attention`, `need-attention`, `needs-attention`

When the SLA logic references a label (e.g., "has 'need more info' label"), match against **all variations** in that group.

## Parent Link Detection

**Use the GitHub sub-issues REST API only.** Do NOT parse the issue body or use GraphQL — these methods miss sub-issue relationships and produce false "no parent" results.

**Preferred — `gh api`:**
```bash
gh api "repos/{owner}/{repo}/issues/{issue_number}/parent" --header "X-GitHub-Api-Version: 2022-11-28"
```
- HTTP 200 → parent exists
- HTTP 404 → no parent link

**Alternative — Direct REST API:**
```
GET https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/parent
Headers:
  Authorization: Bearer {token}
  Accept: application/vnd.github+json
  X-GitHub-Api-Version: 2022-11-28
```

**Alternative — Reference script:** [`scripts/get_parent_issue.py`](../scripts/get_parent_issue.py)
- Requires `GITHUB_TOKEN` or `GH_TOKEN`
- Exit code `0` = parent found, `2` = no parent, `1` = error

## Notification Requirements

When SLA is violated, the notification should include:

1. **Issue identifier**: Number, title, and URL
2. **Repository**: Owner and repo name
3. **Failed criteria**: Specific conditions that were not met
4. **Recommended actions**: What the assignee should do to resolve
