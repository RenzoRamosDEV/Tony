## Why

Tony cannot see its prompt-cache usage or cost (the SDK reports them but Tony discards them), re-asks the model to word identical confirmation questions, and appends the same preference line to the prompt-injected file every time it is saved. These are small, safe sources of wasted tokens and blind spots that make later savings impossible to measure.

## What Changes

- `Usage` gains optional `cache_read_tokens`, `cache_creation_tokens` and `cost_usd`; the Claude engine fills them from the SDK result; the task log's `token_usage` event carries them as additional keys. Unreported cost is `null`, never 0.
- Confirmation wording is cached in memory (128 entries, LRU) by tool, masked arguments, rule, prompt and model; only wording that passes the existing format check is cached; permission decisions are never cached.
- Saving an identical preference line again leaves `memory/preferences.md` unchanged.
- Nothing is removed or renamed; existing events, keys and the task result contract are unchanged.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `task-log`: `token_usage` events carry cache and cost data.
- `guard-confirmation`: confirmation wording is reused for repeated identical questions.
- `conversation-memory`: preferences are written idempotently.

## Impact

- Code: `tony/core/orchestrator/ports.py`, `claude_engine.py`, `runner.py`, `tony/core/events/log_events.py`, `tony/core/guard/claude_wording.py`, `tony/core/memory/preferences.py`.
- Events: `token_usage` log event gains optional keys; the UI `core_events` token event is unchanged. Dependencies: none.
