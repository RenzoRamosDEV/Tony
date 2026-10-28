---
name: regression-testing
description: Use when writing snapshot tests, golden file tests, or regression suites. Covers when golden files are appropriate, file naming and layout, update workflow, handling non-deterministic output, and diff strategies.
---

# Regression Testing

Regression tests prevent known-good behavior from being silently broken. Golden files (snapshot testing) are the primary tool.

## When Golden Files Are Appropriate

- Output is complex, structured, or large: serialized JSON, rendered HTML, generated code, reports
- Manually specifying every field would be brittle and unreadable
- The exact output format is part of the contract

## When NOT to Use Golden Files

- Simple scalar outputs — use a direct assertion instead
- Output is inherently non-deterministic without normalization
- The "golden" state has never been manually verified as correct — a golden file of wrong output is worse than no test

## File Naming and Layout

```
tests/
  __golden__/               # or __snapshots__/, fixtures/golden/
    feature-name/
      test-case-name.json
      test-case-name.html
```

Rules:
- Name files after the **test case**, not the function
- One golden file per test case
- Commit golden files to version control — they are part of the specification

## Update Workflow

1. Run tests — see the diff
2. Decide: is this diff intentional? If yes, proceed. If no, fix the production code.
3. Run the update command (`--update-snapshots`, `--update-golden`, `-u`)
4. Review the updated golden file manually before committing
5. Commit the updated file with a message that explains the behavioral change

**Never auto-update in CI.** Golden file updates are a human decision.

A golden file update is a behavioral change — treat it with the same scrutiny as a code change.

## Handling Non-Deterministic Output

Scrub volatile fields before comparison:
- Timestamps → replace with a fixed string or epoch zero
- UUIDs / generated IDs → replace with a deterministic placeholder
- Session tokens, secrets → redact
- Memory addresses, stack traces → normalize or omit
- Floating point → round to fixed precision

Document what was scrubbed and why in the test, not just in a comment.

## Diff Strategies

| Format | Strategy |
|--------|---------|
| JSON | Pretty-print before comparison; use a JSON-aware differ |
| HTML/XML | Normalize whitespace; use semantic diff tools |
| Plain text | Line-by-line diff is usually sufficient |
| Binary | Compare checksums; store a human-readable representation alongside |

A diff that's hard to read is a golden file that's too large or unstructured — split it or normalize it.
