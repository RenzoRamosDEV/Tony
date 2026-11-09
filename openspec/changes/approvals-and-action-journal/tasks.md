# Tasks

Order is TDD: each group starts with failing tests, then minimal code, then refactor.

## 1. Policy version

- [x] 1.1 Write failing tests: `load_policy_with_version` returns sha256 of file bytes and the same `Policy` as `load_policy`; comment-only edit changes the version; `StaticPolicy`/`LivePolicy.version()`; a failed reload keeps policy and version (`tests/core/guard/test_load_policy.py`, `tests/core/guard/test_edith_policy_source.py`)
- [x] 1.2 Implement in `tony/core/guard/policy.py` and `tony/core/config/reload.py` (`PolicySource.version()`, runner passes the version to `StaticPolicy`); update existing `PolicySource` fakes in tests
- [x] 1.3 Refactor: `load_policy` delegates to the new function; full guard tests green

## 2. Typed previews

- [x] 2.1 Write failing tests in `tests/core/guard/test_previews.py`: fields per tool, 2000/2001 boundary with `…`, absent fields omitted, `bytes` is UTF-8 size of uncut content, secret value and secret-named key masked, unknown tool `args` JSON capped, `attendees` list
- [x] 2.2 Implement `tony/core/guard/previews.py` (`build_preview`); make audit's secret-key masking helper public and reuse it
- [x] 2.3 Refactor: field table as data, no per-tool branches

## 3. Approval binding in guard, broker and events

- [x] 3.1 Write failing tests: `ConfirmationRequest` new optional fields default empty; `needs_confirmation` event includes the five fields when set and omits them otherwise (`tests/core/events/test_core_events.py`)
- [x] 3.2 Write failing guard tests (`tests/core/guard/test_edith_confirm.py`): request has uuid `approval_id`, `args_digest` equal to `args_hash`, `policy_version`, `expires_at` = fake clock + `confirm_timeout_s`, preview; policy swapped to deny during the ask -> `deny` ruling with new rule; swapped but still `confirm` -> second request with new id; three changes -> `user_decision` deny; single audit line carrying `approval_id`, none for allow/deny (`tests/core/guard/test_audit_log.py`)
- [x] 3.3 Write failing broker tests (`tests/core/guard/test_broker.py`): matching id accepted; wrong id ignored and still pending; expired ignored; no id accepted; wrong task ignored; double answer ignored
- [x] 3.4 Write failing command tests: `Confirm` accepts optional `approval_id`, rejects unknown fields; `Runtime._dispatch` forwards it (`tests/core/orchestrator/test_commands.py`, `tests/core/orchestrator/test_runtime_conversations.py` style fake)
- [x] 3.5 Implement: `ConfirmationRequest` fields (`confirm.py`), `needs_confirmation` kwargs (`core_events.py`), `EdithGuard` approval + re-evaluation loop + `clock` + audit `approval_id` (`edith.py`, `audit.py`), `ConfirmationBroker.answer(approval_id)` and expiry (`broker.py`), `Confirm.approval_id` and dispatch (`commands.py`, `runtime.py`), runner passes `deps.clock`
- [x] 3.6 Write failing test then implement `CliConfirmer` printing preview fields to stderr before the question (`tests/core/guard/test_confirm.py`); add optional `approval_id` and fields to desktop TS types and a type-level test in `App.test.tsx`/`reducer.test.ts` only if existing patterns allow, no UI behavior change
- [x] 3.7 Refactor: split `EdithGuard.decide` helpers so each has one reason to change; shipped policy tests unchanged

## 4. Arguments check in the proxy

- [x] 4.1 Write failing tests (`tests/core/orchestrator/test_proxy.py` style with fake guard that mutates args): mutation after ruling -> exact error text, tool not called, supervisor unconfirmed; unchanged args execute; denied path unaffected
- [x] 4.2 Implement the pre/post digest check in `ToolProxy._judge_and_execute`

## 5. Action journal store

- [x] 5.1 Write failing tests `tests/core/memory/test_actions.py`: schema and columns, `prepared` row, transitions update `updated_at`, `detail` masked and 200/201 cut, args never stored, `recover_interrupted` only moves older `dispatched` rows, list filter/limit/newest-first, `get` unknown, missing file handled by read helper
- [x] 5.2 Implement `tony/core/memory/actions.py` (`ActionJournal`, states, `open_journal`) and the `ActionRecorder` Protocol in `tony/core/orchestrator/ports.py`

## 6. Proxy journaling and wiring

- [x] 6.1 Write failing proxy tests with an in-memory recorder fake: success sequence, error reply -> `failed`, exception -> `failed`, timeout -> `outcome_unknown`, denied/unconfirmed/args-changed -> no row, recorder raising -> call still runs and one `error` event, `tony.run_subagent` journaled
- [x] 6.2 Implement journal calls and the `_record` wrapper in `proxy.py`; add `RunDeps.journal` and pass it in `_proxied_tools`
- [x] 6.3 Write failing wiring tests: `Runtime` start and `run_chat`/`run` open the journal, recover interrupted rows once, and close it; nothing replays rows
- [x] 6.4 Implement wiring in `runtime.py`, `apps/cli/chat.py`, `apps/cli/main.py` (`run`)

## 7. CLI `tony actions`

- [x] 7.1 Write failing tests `tests/apps/test_cli_actions.py`: list default/limit/state filter/empty or missing file, bad state and `--limit 0` exit 2, show known/unknown, `outcome_unknown` printed, no recovery side effect
- [x] 7.2 Implement the `actions` Typer group in `tony/apps/cli/main.py` next to `policy` and `conversations`

## 8. Verification

- [x] 8.1 Run the full test suite; confirm no existing test changed except `PolicySource` fakes; flag any test over 10 s
- [x] 8.2 Run mutation testing on the diff only (target above 95%, abort at 3 minutes, justify survivors)
- [x] 8.3 Run `openspec validate approvals-and-action-journal`
