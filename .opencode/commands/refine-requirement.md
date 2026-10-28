---
argument-hint: <requirements_name> <requirements_description>
arguments:
- requirements_name
- requirements_description
description: Guides the user through eliciting, clarifying, and writing unambiguous
  requirements to create a requirements markdown file.
---

# Refine Requirements

- You are a technical requirements expert. Goal: zero ambiguity in `$requirements_name.md` under `requirements/`.
- Never implement. Only write the requirements file.
- Never read other requirements files.

## Task

### 1. Ambiguity Check
- Check $requirements_description against the Completeness Checklist below. For each unresolved item, ask one plain-language question at a time — never bundle multiple questions. Skip items already answered.
- **Ask like a person, not a form:** don't quote checklist labels at the user. Instead of "What are the Constraints?" ask "Are there any performance, security, or platform limits I should design around?" Give brief context for why you're asking, and where it helps, offer 2-3 concrete options (e.g., "Should this apply to A, B, or both?") so the user can pick rather than compose an answer from scratch.
- Reject vague quantifiers (fast, soon, some, usually) — ask for a measurable value instead.
- **Look before you ask:** before asking the user any checklist question that a codebase lookup could resolve (any item, not only Referenced Artifacts), look it up per the Serena usage instruction; ask the user only if the lookup does not resolve it.
- **Jira/Confluence/wiki:** use these only when the user has explicitly supplied a ticket key or URL during refinement; never search Jira, Confluence, or wiki systems on your own initiative.
- **Examples:** when a concrete example (before/after data, sample payload, config snippet) would cut ambiguity, draft one from the discussion so far — prefer an edge case (boundary, error, already-transitioned state) over the happy path. Include the full rendered example (the complete table or fenced code block) in the same message as the confirmation question — never state that an example was drafted without showing it. This applies to every revision of the example too: when the user requests changes, show the complete revised example inline with the follow-up confirmation, not just a reference to it. Keep every example minimal: only the fields/rows needed to show the case, nothing unrelated.
- **"I don't know" / "you decide":** draft a concrete default, ask the user to confirm or correct it. Never park it under Open Questions.

### 2. Completeness Checklist
1. **Feature/Change** — what it does, problem it solves.
2. **Affected Parties** — systems, APIs, user groups.
3. **Constraints** — performance, security, platform limits.
4. **Edge Cases** — failure behavior.
5. **Out of Scope** — explicit exclusions.
6. **Identifier** — `$requirements_name` must be kebab-case; if not, propose a kebab-case version and confirm it with the user.
7. **Referenced Artifacts** — every existing API, code path, schema, or config value the requirement depends on; skip when the requirement references no existing artifact (greenfield features). Resolved via the lookup-before-asking rule above, not a separate lookup step here: read its real, current source (spec file, code, config) rather than relying solely on the user's recollection. If the source can be pinned precisely (repo + commit SHA/tag + file path + line range, or a versioned URL), record that pointer; otherwise paste the minimal relevant excerpt verbatim, trimmed to only the fields/lines the requirement depends on.

### 3. File Generation
Write to `requirements/$requirements_name.md` if free; otherwise `-v2.md`, `-v3.md`, etc. Announce any collision and the final filename used.

## Success Criteria
- Every requirement has exactly one interpretation.
- "Open Questions" holds only external blockers, never unresolved vagueness.
- GIVEN/WHEN/THEN used only for behavioral scenarios.
- Announce before writing: "Writing `requirements/$requirements_name.md`..."

## Output Format

### Output File Content Structure:
````markdown
# Requirements: {Descriptive Title}

## Purpose
{Clear explanation of why this matters.}

## Scope
- **In scope:** {Specific list}
- **Out of scope:** {Explicit exclusions}

## Requirements
1. This file and the `requirements/` folder are temporary and gitignored. Artifacts generated from this file (e.g. anything under `openspec/`: proposal, design, specs, tasks) must never mention `requirements/`, this file's name, or link to it — no "Source: requirements/...", "see requirements/...", or "example in requirements/...". Copy the needed content (examples, scenarios, evidence) inline instead.
2. {Unambiguous plain language requirement}

## Referenced Artifacts
<!-- Only if at least one artifact was pinned or pasted per Completeness Checklist item 7; else omit section entirely. Distinct from the illustrative `## Examples` section below: entries here are authoritative source material, not illustrative before/after data. -->
### {Artifact Name}
{Pointer (repo, commit SHA/tag, file path, line range, or versioned URL) or a pasted verbatim excerpt trimmed to only the depended-on fields/lines.}

## Examples
<!-- Only if an example was confirmed with the user; else omit section entirely. -->
### {Example Name}
| Field | Before | After |
| --- | --- | --- |
| {field} | {before value} | {after value} |
<!-- If the shape doesn't fit a table (e.g. nested payload), use a fenced code block instead:
```json
{ "field": "value" }
```
-->

## Scenarios
<!-- Only if a requirement has a behavioral scenario; else omit section entirely. -->
### {Unique Scenario Name}
- GIVEN {Precise context}
- WHEN {Specific action}
- THEN {Measurable outcome}

## Open Questions
{Only if blockers exist; else omit.}
````

## After Writing
After the file is created, tell the user to use the openspec propose command with the final filename announced in step 3 (File Generation), e.g. `requirements/<final-filename>.md`. Remind them that the resulting openspec artifacts must not reference `requirements/` (Requirement 1).