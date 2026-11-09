## Context

Observed code:
- `HistoryStore` (`tony/core/memory/history.py`): single sqlite `messages` table, content masked on `add`, index on `(conversation_id, id)`. No conversation table: a conversation is its rows.
- `Conversation` holds a fixed `_conversation_id`; `tony chat` (`tony/apps/cli/chat.py`) and `Runtime` (`runtime.py`) each create `uuid4().hex`.
- Core commands are a pydantic discriminated union (`commands.py`) dispatched in `Runtime._dispatch`; events are built in `core_events.py`.
- CLI is Typer (`main.py`, `create_app` with injected factories, `table()` helper, exit codes `USAGE_ERROR=2`, `TASK_FAILED=1`).
- Guard: `evaluate(policy, tool, args)` returns `Verdict(verdict, rule)` by first match; `allow_always.py` has `insert_allow_always` with validate + `_replace` atomic swap; `load_policy` raises `DefinitionError`.
- MCP: `stdio_command` handles bare python; `placeholders.py` has a private regex; voice loader has `REQUIRED_MODULES`; music helpers use `shutil.which("mpv"/"yt-dlp")`.

## Goals / Non-Goals

**Goals:** resume/list/search/delete conversations; local non-executing doctor; policy explain/grants/revoke/simulate; all additive.
**Non-Goals:** desktop picker and diagnostics panel, connection probes, schema migration, changing `evaluate` or shipped policy, restoring any permission state on resume.

## Decisions

1. **No schema change for conversations.** Entries are derived with `GROUP BY conversation_id` (`MAX(id)` for order, `COUNT(*)`, `MAX(ts)`); title = content of the lowest-id `user` row, `[:60]` in Python. Alternative (a `conversations` table) needs a migration for no gain at this scale.
2. **Case-insensitive search in Python-aware SQL.** SQLite `lower`/`LIKE` is ASCII-only; register a small `casefold` containment function on the connection (`create_function`) so `café`/`CAFÉ` match. Empty text returns `[]`. Search runs against stored (masked) content only. `limit` applied after grouping.
3. **Resume = swap the id, nothing else.** `Conversation.resume(id)` sets `_conversation_id`; `handle()` reads the id once into a local at turn start so an in-flight turn keeps its id. `Runtime` validates existence through `HistoryStore` and publishes `error` on unknown id. No replay, no session/broker/policy interaction (invariant from proposal). `DeleteConversation` of the active id is allowed; later messages recreate it (documented, not special-cased).
4. **Events/commands additive.** `ListConversations`, `ResumeConversation{id}`, `DeleteConversation{id}` extend the union; `conversations{items}` builder in `core_events.py`. Delete re-publishes the list.
5. **`--resume [ID]` in Typer.** Option with `is_flag=False, flag_value=""` so bare `--resume` means latest; `run_chat` gains an optional `conversation_id` parameter (default new uuid). Resolution and validation happen in the command before the chat starts (exit 2). Risk: Typer optional-value behavior across versions; a failing-first CLI test pins it; fallback is a separate `--resume-latest` only if the test proves it impossible (would be reported, not silently adopted).
6. **`tony conversations`** is a Typer sub-app like `pin`/`mcp`; a small `open_history(root)` helper builds `HistoryStore` with a masker from `load_variables`. Output via existing `table()`. Unknown delete id -> exit 2.
7. **Doctor in `tony/core/diagnostics/`.** Pure `Check(name, status, hint)` results; checks take injected `which`, `find_spec`, `environ`, `root` so tests use fakes. Modules: `checks.py` (definitions, servers, placeholders, optional deps) and `report.py` (table + exit code, reusing the CLI `table`-style formatting via a plain function to keep core free of CLI imports). Definitions check iterates `agents/*` with existing loaders (`load_config`, `load_agent`/`parse_tool_spec`, `load_policy`) catching `DefinitionError` per file. Optional voice check uses `importlib.util.find_spec` (no import, so no heavy module execution), module list reused from the voice loader's `REQUIRED_MODULES`. Placeholders: add a public `placeholder_names(value) -> set[str]` to `placeholders.py` (wraps the existing regex) and compare with `load_variables(...).values`; only names enter hints.
8. **Policy tooling in `tony/core/guard/`.** `explain` calls `evaluate` and finds the index by rule identity from `policy.rules` (first match position, reusing `rule_matches` logic through `evaluate`'s returned rule id; duplicate ids resolve to the first, equal to first-match). `grants` filters `ALLOW_ALWAYS_PREFIX`. `revoke_allow_always(root, guard, tool)` is added beside `insert_allow_always` and shares its load -> mutate -> `Policy.model_validate` -> `_replace` path; returns whether a rule was removed, writing nothing when none. `simulate` is a pure function over a parsed case list returning per-case results. All CLI-only: not registered as native tools or core commands.

## Risks / Trade-offs

- PyYAML rewrite drops comments (already accepted for insert); revoke inherits it. Mitigated: validation before swap, file untouched on failure.
- `revoke` removes only ids with the `user-always/` prefix, so shipped rules can never be deleted by it.
- Search is a full scan of messages; acceptable for a personal local store, no index added (YAGNI).
- Doctor `find_spec` can report a module present that fails at import (e.g. missing PortAudio); stated in the hint, deeper probes are out of scope.
- Interleaving: resume while a turn runs is safe by capturing the id per turn.

## Migration Plan

No data migration; additive commands/events/CLI. Rollback is reverting the code; existing sqlite and policy files remain valid.

## Testing Strategy

Failing tests first, fakes preferred: real sqlite in `tmp_path` for the store, fake `which`/`find_spec`/environ for the doctor, tmp policy files for revoke (byte comparison on failure paths), Typer `CliRunner` for CLI with injected factories. Boundary tests: title length 59/60/61, limit 20/21, empty search text, case/accent folding. Mutation testing on the diff only (>95%).

## Open Questions

None.
