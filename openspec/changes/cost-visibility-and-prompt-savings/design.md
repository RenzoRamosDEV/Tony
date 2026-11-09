## Context

Observed: `Usage` holds only input and output tokens; `outcome_from_messages` reads `final.usage` and discards cache keys and `total_cost_usd`; `runner.py` logs `log_events.token_usage(input_tokens, output_tokens)` and publishes the UI token event. `ClaudeWording.word` calls the SDK on every confirmation and `worded_question` validates the result afterwards. `PreferencesFile.append_line` appends unconditionally.

## Decisions

1. **Defaults keep constructors working.** `Usage(input, output, cache_read_tokens=0, cache_creation_tokens=0, cost_usd=None)`. The accumulator reads `cache_read_input_tokens`, `cache_creation_input_tokens` and `total_cost_usd` defensively. Only `log_events.token_usage` gains keys (via optional keyword args); the UI `core_events` token event and `Supervisor.record_usage` are unchanged (alert math stays input+output).
2. **Wording cache wraps the validated path.** A `CachingWording` decorator implementing `QuestionWording` around `ClaudeWording` stores a result only when it matches the same format regex used by `worded_question` for the given rule (shared helper `is_valid_question(text, rule)` extracted from `worded_question`). It uses an `OrderedDict` LRU of 128. Key includes system prompt and model id so a prompt change invalidates entries. Timeouts/errors propagate unchanged and are not stored. Verdicts are untouched.
3. **Idempotent append.** `append_line` compares the masked, normalised line against existing lines (stripped of the leading `- `); equal → return without writing.

## Risks / Trade-offs

- Stale wording after an Edith prompt edit → key includes the prompt text.
- Cost field semantics → `null` means unknown; consumers must not treat it as 0.
- Cache key built from the masked preview only, so secrets never enter the cache.
