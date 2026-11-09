## 1. Cost and cache accounting (task-log)
- [x] 1.1 Write failing tests: `Usage` defaults; accumulator fills cache and cost, `None` cost when absent; `token_usage` log event carries the new keys and keeps the old ones
- [x] 1.2 Extend `Usage`, `OutcomeAccumulator`, `log_events.token_usage` and the `runner.py` call site

## 2. Wording cache (guard-confirmation)
- [x] 2.1 Write failing tests: second identical question makes no model call; invalid/empty/failed wording not cached; different args, rule, prompt or model miss; LRU eviction at 128; verdicts unaffected
- [x] 2.2 Extract `is_valid_question`, implement `CachingWording` and wire it where `ClaudeWording` is built

## 3. Idempotent preferences (conversation-memory)
- [x] 3.1 Write failing tests: exact duplicate leaves the file byte-identical; different case or text appends; masked secrets compared after masking; existing duplicates untouched
- [x] 3.2 Implement the check in `PreferencesFile.append_line`

## 4. Verification
- [x] 4.1 Run the full suite and mutation testing on the diff (>95 %, abort at 3 min)
