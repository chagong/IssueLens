# SLA Script I/O Contract

This file is the **specification** that a freshly generated `sla_check.py` MUST
satisfy. The script is generated on every workflow run by Copilot CLI from the
*target repository's* `.github/sla.md` policy, written to a temporary folder,
verified against a fixture, and then run over the real issues. It is never
committed.

The contract is intentionally repo-agnostic: only the **policy logic** changes
between repositories — the command-line interface, the input shape, and the
output shape below never change.

## Command-line interface

```
python sla_check.py --input <issues.json> --output <scored.json>
```

- `--input`  Path to a JSON array of issue objects (see *Input*).
- `--output` Path to write the scored JSON array (see *Output*). May be the
  same path as `--input` (overwrite in place).

The script reads a GitHub token from the `GH_TOKEN` or `GITHUB_TOKEN`
environment variable. A token is only required when it needs to call the GitHub
API (e.g. parent-link detection). It MUST NOT crash if the token is missing —
in that case it should treat un-determinable signals conservatively.

The script MUST exit `0` on success and non-zero only on an unrecoverable error
(e.g. malformed input file). A single per-issue API failure MUST NOT abort the
whole run — degrade gracefully for that issue and continue.

## Input

A JSON array. Each element is an issue object with at least these fields:

| Field          | Type        | Notes                                            |
|----------------|-------------|--------------------------------------------------|
| `repo`         | string      | `owner/name`                                     |
| `issue_number` | integer     | Issue number                                     |
| `title`        | string      | Issue title                                      |
| `url`          | string      | Issue HTML URL                                   |
| `assignees`    | string[]    | Assignee logins                                  |
| `labels`       | string[]    | Label names (raw, mixed-case)                    |
| `createdAt`    | string      | ISO-8601 timestamp, e.g. `2026-01-02T03:04:05Z`  |
| `updatedAt`    | string      | ISO-8601 timestamp                               |
| `has_parent`   | boolean?    | **Optional.** See *Parent-link detection*.       |

The script MUST tolerate extra unknown fields and pass them through unchanged.

## Output

The **same** array, in the **same order**, with each issue object augmented
with exactly these three additional fields:

| Field         | Type    | Allowed values / notes                              |
|---------------|---------|-----------------------------------------------------|
| `sla_status`  | string  | One of `GOOD`, `WARNING`, `VIOLATION` (UPPERCASE).  |
| `days_open`   | integer | Whole days the issue has been open (>= 0).          |
| `sla_details` | string  | One short sentence explaining the verdict.          |

All other fields from the input MUST be preserved. Do not drop assignees,
labels, url, etc. — the notification step depends on them.

> A policy may only ever produce `GOOD` and `VIOLATION` (no `WARNING`). That is
> fine — `WARNING` is *allowed* by the contract but not *required*.

## Parent-link detection

If an input issue object contains a boolean `has_parent` field, the script MUST
use that value directly and MUST NOT make any network call for that issue. This
keeps the fixture verification fully offline and deterministic.

Otherwise, determine the parent link via the GitHub sub-issues REST API:

```
GET https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/parent
Headers:
  Authorization: Bearer {token}
  Accept: application/vnd.github+json
  X-GitHub-Api-Version: 2022-11-28
```

- HTTP `200` → a parent exists.
- HTTP `404` → no parent.
- Any other error → treat as "no parent" but do not crash.

Do **not** parse the issue body or use GraphQL for parent detection.

## Label matching

Match labels **case-insensitively**. Honor every spelling variation the policy
lists as equivalent (e.g. `need attention`, `needs attention`, `need-attention`,
`needs-attention` are the same label). Normalize by lower-casing and treating
`-` and spaces as equivalent when the policy groups such variations.

## Policy source

The actual rules (exempt labels, tolerance window, required conditions, and how
status is decided) come from the target repository's `.github/sla.md`. Implement
exactly what that document specifies. If the document is missing, fall back to a
reasonable default (exempt "needs more info"/"needs log" → GOOD; within the
tolerance window → GOOD; otherwise GOOD only if a parent link exists and there
is no "needs attention" label, else VIOLATION).
