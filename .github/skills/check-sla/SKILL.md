---
name: check-sla
description: Check SLA (Service Level Agreement) status for GitHub issues by generating and running a deterministic Python script from the repository's SLA policy. Use when (1) verifying SLA compliance for one or many issues, (2) checking if issues meet SLA requirements, (3) generating SLA status reports, (4) evaluating SLA at scale for hundreds of issues. Triggers on requests like "check SLA", "SLA status", "verify SLA compliance", "are issues meeting SLA".
---

# Check SLA Skill

Evaluate the SLA (Service Level Agreement) status of GitHub issues — for one
issue or many thousands — **without asking the AI to judge each issue**.

Instead, the AI reads the SLA policy once, **generates a deterministic Python
script** that encodes that policy, **verifies** the script against a fixed
fixture, and then **runs** the script over any number of issues. The AI's job is
to author and validate a correct script; the script does the actual SLA
classification. This makes evaluation:

- **Scalable** — one script run handles hundreds/thousands of issues; no
  per-issue AI calls, no GitHub Actions matrix limits.
- **Cheap & fast** — a single generation step, then pure Python execution.
- **Deterministic & auditable** — the same inputs always produce the same
  verdicts, and the logic can be inspected.
- **Repo-agnostic** — only the policy logic changes per repository; the
  interface and input/output shapes are fixed.

## When to use this skill

Use it whenever you need SLA verdicts for GitHub issues. The same flow works for
a single issue and for an entire backlog — you just pass a 1-element or
N-element issue array to the generated script.

## SLA policy source

The policy that the generated script encodes comes from the **target**
repository's `.github/sla.md`. When that file is **missing**, the script must
implement the **default SLA strategy** documented in
[references/default-sla.md](references/default-sla.md) — exempt labels,
required conditions, label-variation matching, and parent-link detection. Read
the applicable policy (target `.github/sla.md` or, as fallback,
[references/default-sla.md](references/default-sla.md)) before generating.

## Overview of the flow

```
target .github/sla.md  ── or fallback ──►  references/default-sla.md
        │                                            │
        └──────────────────┬─────────────────────────┘
                           ▼                    fixtures/ (this skill)
                  (the SLA policy)                     │
                           │                           ▼
1. Read policy ──► 2. Generate ──► 3. Verify (gate) ──► 4. Run over all issues
                    sla_check.py     verify_generated.py    sla_check.py
                    (temp, uncommitted)  must exit 0        --input ... --output ...
```

1. **Read the policy** from the target repository's `.github/sla.md`, or fall
   back to [references/default-sla.md](references/default-sla.md) if it is
   missing.
2. **Generate** a self-contained `sla_check.py` into a temporary directory that
   encodes that policy and conforms to the I/O contract.
3. **Verify** the generated script with the deterministic gate. If it fails,
   regenerate and verify again — never trust an unverified script.
4. **Run** the verified script over the real issues to produce scored output.

## Inputs and outputs

- **Input to the skill:** the target repository (`owner/repo`) and a JSON array
  of issues to evaluate (see the I/O contract for the exact issue shape). A
  single-issue request is just an array of length 1.
- **Output of the skill:** the same JSON array, with each issue augmented with
  `sla_status` (`GOOD` | `WARNING` | `VIOLATION`), `days_open` (integer), and
  `sla_details` (one-sentence explanation).

The exact, fixed contract the generated script MUST satisfy is defined in
[references/IO_CONTRACT.md](references/IO_CONTRACT.md). Read it before generating.

## Step 1 — Read the SLA policy

Fetch `.github/sla.md` from the **target** repository (GitHub MCP tools or
`gh api`). Parse its rules: exempt labels, tolerance window, required conditions,
label-name variations, and the parent-link rule.

If `.github/sla.md` is not found, use the default SLA strategy documented in
[references/default-sla.md](references/default-sla.md) as the policy to encode.

## Step 2 — Generate the script

Write a self-contained Python 3 (stdlib-only) script named `sla_check.py` into a
temporary working directory. **Do not commit it** — it is regenerated every run.

- Use [references/example_sla_check.py](references/example_sla_check.py) as the
  structural template. Keep its command-line interface, input parsing, output
  writing, the `has_parent` offline shortcut, the case-insensitive label-group
  matching helpers, and the graceful per-issue error handling.
- Replace **only** the policy logic in `evaluate()` with exactly what the target
  repository's `.github/sla.md` specifies.
- The script MUST conform to [references/IO_CONTRACT.md](references/IO_CONTRACT.md):
  same CLI (`--input` / `--output`), same input issue shape, and it must add
  `sla_status`, `days_open`, and `sla_details` while preserving every existing
  field (assignees, labels, url, …).

Keep the script dependency-free (Python standard library only) so it runs in any
CI environment without `pip install`.

After writing the script, you MUST proceed to Step 3 and verify it yourself.
Generation is not done until the verifier passes.

## Step 3 — Verify before trusting it (mandatory gate, you run it)

Do **not** rely on your own judgement that the script is correct. **You** must
run the deterministic verifier and read its exit code — the verifier, not your
opinion, decides whether the script is correct:

```bash
python <skill>/scripts/verify_generated.py \
  --script <tmp>/sla_check.py \
  --fixture <skill>/fixtures/sample_issues.json \
  --expected <skill>/fixtures/expected_output.json \
  --workdir <tmp>
```

The verifier runs `sla_check.py` against a fixture with known-correct verdicts
(fully offline — the fixture supplies `has_parent`, so no token or network is
needed), and checks:

1. the script runs without error and exits 0;
2. output is a JSON array of the same length and order as the input;
3. every issue has a valid `sla_status`, an integer `days_open >= 0`, and a
   non-empty `sla_details`;
4. every issue's `sla_status` matches the expected verdict (this also exercises
   case-insensitive label-variation matching);
5. original fields are preserved.

It exits **non-zero** if the generated script is broken or wrong, and prints
exactly which issues failed. **This is an iterate-until-green loop:** if the
verifier exits non-zero, read its output, fix `sla_check.py`, and run the
verifier again. Repeat until it exits `0`. Only a script that you have seen the
verifier pass is allowed to leave this skill — never hand off an unverified or
failing script.

### Fixture invariants

The fixture in `fixtures/` encodes policy-independent SLA invariants that hold
for any reasonable SLA policy (and for the default strategy):

| Issue | Condition                                            | Expected   |
|-------|------------------------------------------------------|------------|
| 1001  | Exempt label (`needs more info`)                     | GOOD       |
| 1002  | Brand-new, inside grace window                       | GOOD       |
| 1003  | Old, has parent, no attention label                  | GOOD       |
| 1004  | Old, has parent, but `needs attention`               | VIOLATION  |
| 1005  | Old, no parent                                        | VIOLATION  |
| 1006  | Old, has parent, attention label in different casing | VIOLATION  |

Timestamps use `{{NOW}}` / `{{NOW-Nd}}` placeholders so the expected verdicts
stay stable no matter when the run happens. If a target policy genuinely
contradicts one of these invariants, update `fixtures/sample_issues.json` and
`fixtures/expected_output.json` to match that policy, then regenerate.

## Step 4 — Run over all issues

Once verification passes, evaluate every real issue in one pass:

```bash
python <tmp>/sla_check.py --input issues.json --output scored.json
```

`issues.json` is the array of issues to evaluate; `scored.json` is the same
array with `sla_status` / `days_open` / `sla_details` added. The output feeds
directly into downstream steps (e.g. notifying assignees of `VIOLATION` issues).
For SLA evaluation at scale the script needs a `GH_TOKEN` / `GITHUB_TOKEN` to
resolve parent links via the GitHub API; a single per-issue API failure degrades
gracefully for that issue rather than aborting the run.

## Default SLA Strategy

When the target repository has no `.github/sla.md`, the generated script must
implement the default strategy defined in
[references/default-sla.md](references/default-sla.md) (exempt labels, tolerance
window, required conditions, label-variation matching, and parent-link
detection). Use that document as the policy source for generation.

## Label Matching

Match labels **case-insensitively**, and treat spelling variations within a
group as identical (normalize by lower-casing and treating `-` and spaces as
equivalent):

- **"need more info"** group: `need more info`, `needs more info`,
  `need-more-info`, `needs-more-info`
- **"need log"** group: `need log`, `needs log`, `need-log`, `needs-log`
- **"need attention"** group: `need attention`, `needs attention`,
  `need-attention`, `needs-attention`

When the policy references a label, match against **all variations** in its
group. The example template includes ready-to-use `normalize_label()` and
`label_in_group()` helpers.

## Parent Link Detection

**IMPORTANT:** Parent links are managed through GitHub's sub-issues API. Do NOT
detect parent links by parsing issue body text, checking for "tracked-by"
keywords, or using GraphQL — those are unreliable and produce false negatives.

In the generated script, prefer an explicit `has_parent` boolean on the input
issue when present (this is what makes fixture verification offline). Otherwise
call the REST API:

```
GET https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/parent
Headers:
  Authorization: Bearer {token}
  Accept: application/vnd.github+json
  X-GitHub-Api-Version: 2022-11-28   # Required — omitting this may cause detection to fail
```

- HTTP `200` → parent exists.
- HTTP `404` → no parent.
- Any other error → treat as "no parent" but do not crash.

A reference helper for ad-hoc checks is available at
[scripts/get_parent_issue.py](scripts/get_parent_issue.py) (exit `0` parent
found, `2` no parent, `1` error; requires `GITHUB_TOKEN`/`GH_TOKEN`).

## Files in this skill

| Path                                   | Purpose                                                        |
|----------------------------------------|---------------------------------------------------------------|
| `references/IO_CONTRACT.md`            | The fixed CLI + input/output contract the script must satisfy. |
| `references/example_sla_check.py`      | Structural template to copy; replace only the policy logic.    |
| `references/default-sla.md`            | Detailed default SLA criteria.                                 |
| `scripts/verify_generated.py`          | Deterministic gate that verifies a generated script.           |
| `scripts/get_parent_issue.py`          | Reference parent-link helper.                                  |
| `fixtures/sample_issues.json`          | Offline fixture (uses `{{NOW}}` placeholders, `has_parent`).   |
| `fixtures/expected_output.json`        | Expected verdicts for the fixture.                             |

## Quick start (end to end)

```bash
SKILL=.github/skills/check-sla
TMP=$(mktemp -d)

# 1. (AI) read target repo .github/sla.md
# 2. (AI) write $TMP/sla_check.py from references/example_sla_check.py + policy

# 3. verify — must exit 0
python "$SKILL/scripts/verify_generated.py" \
  --script "$TMP/sla_check.py" \
  --fixture "$SKILL/fixtures/sample_issues.json" \
  --expected "$SKILL/fixtures/expected_output.json" \
  --workdir "$TMP"

# 4. run over real issues
python "$TMP/sla_check.py" --input issues.json --output scored.json
```

## Using this skill from automation (CI)

When a workflow invokes this skill (e.g. via the Copilot CLI), the prompt should
stay thin and just point here — all the detail lives in this file. The skill's
deliverable in that mode is a **verified** script at a path the caller chooses
(e.g. `sla-gen/sla_check.py`). Concretely, when asked to "use the check-sla
skill to produce a verified SLA script for `<owner/repo>` at `<output-path>`",
you must:

1. Read the policy (Step 1): the target repo's `.github/sla.md`, or
   [references/default-sla.md](references/default-sla.md) if it is absent.
2. Generate the script (Step 2) at `<output-path>`.
3. **Run the verifier yourself and iterate until it exits `0`** (Step 3). Do not
   finish while the verifier is failing.
4. Leave the final, verifier-passing script at `<output-path>`. Do not evaluate
   the real issues yourself and do not modify any other file — the calling
   workflow runs the verified script over the real issues itself (and re-runs
   the verifier once more as an independent gate).

This keeps the workflow's prompt to a single sentence while guaranteeing the
script was actually proven correct against the fixture before anything relies on
it.

## Example Requests

- "Check SLA for issue #123 in microsoft/vscode" (array of 1)
- "Evaluate SLA for all open issues in owner/repo" (array of N)
- "Verify SLA status for these 600 assigned issues"
