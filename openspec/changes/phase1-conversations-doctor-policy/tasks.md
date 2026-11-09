## 1. Conversation store (tests first)

- [x] 1.1 Write failing tests in `tests/core/memory/` for `list_conversations` (order, title cut at 59/60/61 chars, count, last_ts, limit 20, empty), `search_conversations` (case/accent folding, masked-only, empty text, dedupe, limit) and `delete_conversation` (only that id, bool result)
- [x] 1.2 Implement the three methods in `tony/core/memory/history.py` (group-by queries, containment function on the connection); refactor

## 2. Core commands and events (tests first)

- [x] 2.1 Write failing tests: `parse_command` for the three new commands (missing `id` rejected), `core_events.conversations` shape, `Conversation.resume` switches the stored id and keeps history budget, in-flight turn keeps its id, `Runtime` list/resume/delete publish events and `error` on unknown id, resume touches no session/broker/policy state
- [x] 2.2 Implement commands in `commands.py`, event builder in `core_events.py`, `Conversation.resume` plus per-turn id capture in `conversation.py`, dispatch in `runtime.py`

## 3. CLI conversations (tests first)

- [x] 3.1 Write failing CLI tests: `tony conversations list|search|delete` (table, empty, unknown id exit 2) and `tony chat --resume ID` / bare `--resume` / unknown id exit 2 / no conversations exit 2 / permissions asked again after resume
- [x] 3.2 Implement the `conversations` sub-app and `--resume` option in `tony/apps/cli/main.py`; add optional `conversation_id` to `run_chat` in `tony/apps/cli/chat.py`

## 4. Doctor (tests first)

- [x] 4.1 Write failing tests in `tests/core/diagnostics/` with fakes for `which`, `find_spec`, environ: definitions ok/fail (one broken file does not stop others), stdio command missing/bare python, HTTP scheme, undefined placeholder (names only, value never printed), voice `warn`, music `yt-dlp`/`mpv` only when `music` declared, no subprocess/socket, report table and exit code (fail -> 1, warn -> 0)
- [x] 4.2 Add `placeholder_names` to `tony/core/config/placeholders.py` with a test
- [x] 4.3 Implement `tony/core/diagnostics/` (`checks.py`, `report.py`) and the `tony doctor` command; add a CLI test for the table and exit codes

## 5. Policy inspector (tests first)

- [x] 5.1 Write failing tests in `tests/core/guard/`: explain (rule match, 1-based position, default, bad args exit 2), grants (two, none), `revoke_allow_always` (other rules/keys/order preserved, unknown grant -> False and bytes unchanged, shipped rule id not removable, write failure leaves file), simulate (all pass, one fail, malformed case index, exit codes), and a guard that no policy command is a native tool or core command
- [x] 5.2 Implement explain/grants/simulate helpers and `revoke_allow_always` in `tony/core/guard/` reusing the validate + `_replace` path; add `tony policy` sub-app in `main.py`

## 6. Verification

- [x] 6.1 Confirm `agents/edith/policy.yaml` and `tests/core/guard/shipped_policy.py` are unchanged and `evaluate` is untouched
- [x] 6.2 Run the full suite (flag any test over 10 s) and mutation testing on the diff only (>95%, justify survivors)
