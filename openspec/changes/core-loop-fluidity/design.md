## Context

Observed in the current code: `runtime._publish_audio_devices` calls `list_devices()` synchronously (it shells out to `pw-dump`, timeout 5 s); `Listener._transcribe` checks `session is self._session` only after `Stt.transcribe`; `ClaudeEngine.run/converse` collect every SDK message into a list before `outcome_from_messages`; `read_skill_body` calls `list_skills`, which parses every `SKILL.md`.

## Goals / Non-Goals

**Goals:** remove the blocking and wasted work above with identical observable behavior.
**Non-Goals:** new features, changing events, streaming TTS, MCP changes.

## Decisions

1. **Discovery via `asyncio.to_thread` + shared task.** `_publish_audio_devices` becomes a coroutine-driven flow: the runtime keeps `self._discovery: asyncio.Task | None`; a new request awaits/joins it, then publishes with the warnings captured at request time. The task is tracked in the runtime's task set and cancelled on shutdown; publish is skipped if the runtime is closed. Alternative (thread + callback) rejected: harder to cancel.
2. **Skip before inference.** In `Listener._transcribe`, return early (still calling `_end(session)`) when `session is not self._session`. Keep the post-inference check. Queued obsolete items drain through the same cheap path, so no queue purge API is needed.
3. **Incremental accumulator.** Add `OutcomeAccumulator` with `add(message)` and `outcome()`, tracking `last_text` and `final`. `outcome_from_messages` delegates to it (same results, including error and missing-result cases). `run`/`converse` feed messages as they arrive instead of building a list.
4. **Direct skill lookup.** `read_skill_body` accepts only names that are plain child directory names (no separators, not `.`/`..`), parses `skills/<name>/SKILL.md` if it exists, and returns `None` otherwise (the caller keeps using `list_skills` for the "available" list).

## Risks / Trade-offs

- Cancellation races in discovery → generation counter; late results dropped.
- Session end-exactly-once in the listener → covered by tests for both pre- and mid-inference cancellation.
- Skill validation difference → a skill whose frontmatter is invalid is still treated as not found (parse error → `None`), matching the old listing that skipped invalid skills.
