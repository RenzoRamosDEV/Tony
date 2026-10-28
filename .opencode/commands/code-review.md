---
argument-hint: <code_review_name> <commit>
arguments:
- code_review_name
- commit
description: Runs a structured architecture/best-practices/test-coverage/code-smell
  review, delegating each aspect to the best-matching available agent, runs the project's
  local test suite(s), and writes an English findings report to `./code-reviews/`.
---

# Code Review

- You are a code review orchestrator. Goal: produce a structured findings report at `./code-reviews/$code_review_name.md`.
- You only report findings — never edit, patch, or fix any reviewed code, and never post the report anywhere other than the local report file (no Jira comment, PR comment, Slack message, or similar).

## Task

### 1. Resolve Review Scope
- Check whether `$commit` was provided.
- **If provided:** verify it resolves to a valid ref in the repository (e.g. `git rev-parse --verify $commit^{commit}`).
  - **If it does not resolve:** stop immediately with an error ("`$commit` does not resolve to a valid ref in this repository.") and produce no output file. Do not evaluate anything.
  - **If it resolves:** scope the review to exactly `git diff $commit..HEAD` — committed changes only, excluding uncommitted working-tree changes. Skip the whole-project warning below.
- **If omitted:** warn the user that the entire project will be evaluated, then block on an explicit Yes/No confirmation, reusing the confirm-before-proceeding pattern:
  - Ask: "No commit given — this will review the entire project. Continue? (Yes/No)"
  - **No:** abort immediately. Do not evaluate the project and do not write any file.
  - **Yes:** proceed to evaluate the entire project across all four review aspects below.

### 2. Delegate Each Aspect
For each of these four aspects — architecture; technology-stack best practices; test coverage and design; code smells — do the following, per `.claude/rules/agent-delegation.md`:
- Check the `description` of every currently-available specialized agent and identify whichever one's description best semantically matches that aspect's primary intent. Never hardcode a fixed agent name/type as the reviewer for an aspect — re-evaluate the match live against whatever agents are currently available each time this prompt runs.
- Before delegating, check the description of every currently-available skill and identify whichever one's description best matches that aspect's purpose, matched live each run and never by a hardcoded skill name.
- **If a match is found (agent):** delegate that aspect's review to the matched agent, scoped to the diff/project scope resolved in Task 1. Instruct it to return findings only (aspect tag, severity, `file:line`, one-sentence issue, one-sentence fix) — it must not edit any code. If a skill also matches this aspect, instruct it to invoke and follow the matched skill while producing its findings. If no skill matches, proceed without blocking.
- **If no agent matches:** review that aspect yourself directly, and record in the report that no delegate was available for it. If a skill matches this aspect, follow that skill's method for the review instead of ad hoc judgment; if none matches, proceed without blocking.

### 3. Run Local Tests
Once per review, independent of the four aspects above, detect and run the project's local test suite(s):
- Detect by presence of a marker file at the repository root only (not subdirectories):

| Marker | Command |
|--------|---------|
| `gradlew` | `./gradlew test` |
| `package.json` | `npm test` |
| `pyproject.toml` or `setup.py` | `pytest` |
| `go.mod` | `go test ./...` |
| `Cargo.toml` | `cargo test` |
| `pom.xml` | `mvn test` |

- When more than one marker is present, run every detected command without asking the user and without picking only one.
- `pyproject.toml` and `setup.py` together count as one detected tool: run `pytest` once, not twice.
- Run the full local suite for each detected command; this is not scoped to the diff.
- Cap each command at a 5-minute timeout (e.g. the executing tool's own timeout, or `timeout 300 <cmd>`). If a command exceeds the cap, abort it, record it as timed out in the report, and continue the review with the remaining steps.
- If no marker file is found at the repository root, skip this step entirely and note in the report that no local test tool was detected.
- Before running and interpreting results, check currently-available skills' descriptions for one matching test-execution or interpretation purpose, matched live each run and never by a hardcoded skill name, and follow it when running and interpreting results. If none matches, proceed without blocking.

### 4. Assemble the Report
- Write the report entirely in English, regardless of the language of the reviewed code or its commit messages.
- Open with a short header: the scope reviewed (the commit range, or "whole project") and the finding counts by severity (High/Medium/Low).
- Before listing findings, drop any finding whose `file:line` is not grounded in the reviewed scope: the file must be in the reviewed diff or files, and the line must exist within that file. This grounding check applies to every finding source — delegated aspects, self-review, and test failures.
- List every finding in exactly this one-line form, grouped by aspect: aspect tag, severity (High/Medium/Low), `file:line`, one-sentence issue description, one-sentence suggested fix. No longer narrative form.
- For any aspect with no available delegate (Task 2), note that next to that aspect's findings in the report.
- Include one summary line per detected test command with its pass/fail/timeout counts. For each failing test with a resolvable location, add one finding line tagged `tests` in the standard format above; a failing test without a resolvable location counts in the summary only.
- If no local test tool was detected, or a command timed out, include that note in the report as well, mirroring the "no delegate available" note.
- Never name the agent or skill that produced any finding, anywhere in the report.

### 5. Write the Output
- Create the `./code-reviews/` directory if it doesn't exist.
- Write the report to `./code-reviews/$code_review_name.md` if that path is free; otherwise `-v2.md`, `-v3.md`, etc. — never overwrite.
- Announce the final filename used to the user.