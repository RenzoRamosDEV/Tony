# Code Review — Verificar

**Scope:** whole project (no commit ref given; full-project review confirmed by user)
**Findings:** High: 1 · Medium: 5 · Low: 6

## architecture

No findings. A dedicated audit traced every apparent `tony/core` → `tony/apps` coupling signal back to source and confirmed each one was a false positive (identifier-name collision in the dependency graph, not a real import). `tests/test_architecture.py` already enforces AST-based layering guards (forbidden imports of `tony.apps`, `typer`, `fastapi` from `tony.core`; web/cli isolation; voice engine isolation) covering this finding class. The agent-folder convention (`agents/viernes`, `agents/jarvis`, their skills and subagents) is fully compliant with `openspec/specs/agent-folder-convention/spec.md`. Frontend (TSX) layering was not separately audited — out of scope for this pass.

## tech-stack best practices

*No specialized agent or skill matched this aspect's full scope (mixed Python/React stack); reviewed directly by the orchestrator.*

- tech-stack | Low | tests/agents/test_bundled_agents.py:32 | Three lines exceed the project's own ruff `line-length = 100` (ruff check reports E501 at lines 32, 44, 264). | Wrap the long f-string/assert lines to fit within 100 columns.
- tech-stack | Medium | tony/apps/web/frontend/package.json:9 | The frontend `lint` script only runs `tsc --noEmit`; there is no ESLint (or equivalent) configuration enforcing React/TS style and correctness rules beyond type-checking. | Add an ESLint config (e.g. `eslint` + `typescript-eslint` + `eslint-plugin-react-hooks`) and wire it into the `lint` script.

## tests

- tests | High | tony/core/runner/portable_native.py:1 | `PortableNativeTools` — the adapter exposing native tools to non-Claude engines, central to this branch's pluggable-engines goal — has zero references anywhere in `tests/`. | Add a unit test using the existing `RecordingHandlers` fake from `tests/core/test_native_tools.py` asserting `.catalog` exposes the expected `ToolRef`s and `.call()` dispatches correctly, including an unknown-tool error case.
- tests | Medium | tony/core/runner/factory.py:19 | `default_worker_runner_factory` wires `ClaudeSdkRunner` with no direct test asserting settings/task_id/gate/call/token/native_handlers are passed through correctly. | Add a unit test instantiating it with stub args and asserting the constructed runner received them, or fold into `test_engine_factory.py` if already covered there.
- tests | Low | tony/core/voice/engines/faster_whisper.py:1 | The real voice-engine adapters (faster_whisper, kokoro, piper, silero) have no adapter-level unit tests of their own beyond the registry/real-engine smoke tests. | Add a cheap per-adapter unit test with a stub for the underlying library to verify config-to-kwargs wiring, without requiring the real model.
- tests | Low | tests/apps/web/test_hub.py:1 | This file (813 lines) and `tests/core/channels/test_chat_session.py` (1043 lines) each cover many distinct behavior areas through one shared harness fixture, making it easy for a future addition to silently duplicate an existing equivalence class. | Split each into topic-based modules (e.g. `test_hub_hello.py`, `test_hub_turns.py`) sharing the harness via a local `conftest.py`.

## code smells

- code-smell | Medium | tony/apps/web/hub.py:451 | `configure_engine` and `change_engine` both duplicate the literal path expression for `engine-auth.json` before calling `save_engine_auth`. | Extract a `ChatRuntime.engine_auth_path` property used by both call sites.
- code-smell | Medium | tony/apps/web/hub.py:1 | `ConversationHub` (705 lines) mixes websocket lifecycle, audio/voice session management, engine hot-swap, confirmation routing, and outbound queue pumping in one class with well over a dozen responsibilities. | Extract engine configuration/switching into an `EngineSwitcher` collaborator, and consider extracting audio-session orchestration into its own component.
- code-smell | Medium | tony/core/runner/auth.py:39 | The `{"forceLoginMethod": "claudeai", "apiKeyHelper": ""}` settings dict is duplicated between `claude_account_options` and `require_credentials`. | Hoist it to a module-level constant and reuse via `json.dumps(...)` in both places.
- code-smell | Low | tony/core/runner/auth.py:23 | `account_env` branches on `engine == "claude_sdk"` twice, making the control flow slightly harder to read than necessary. | Split into two small dict-building branches or pair the var list with its clear/pop action in one structure.
- code-smell | Low | tony/core/runner/engine_factory.py:30 | `build_runner_factory` and `build_conversation` repeat an identical if/elif/elif/raise ladder keyed on the same three engine-type strings. | Collapse into a registry dict keyed by engine type, looked up with a single `.get(...)`.
- code-smell | Low | tony/core/channels/session.py:365 | `_redacted`'s generic TypeVar method signature adds typing ceremony for a single internal use with two call sites. | Inline the redact/round-trip at the two call sites or use a plain non-generic private helper.
- code-smell | Low | tony/apps/web/hub.py:230 | Turn admission/cancellation state is tracked independently in both `ConversationHub` (`self.turn`) and `ChatSession` (`self._turn`), two sources of truth for "is a turn busy". | Have `ConversationHub` query `ChatSession.turn_in_progress` directly instead of maintaining a parallel task flag.

## tests (suite run)

- Detected tool: `pyproject.toml` → `pytest`. Result: **5 failed, 1734 passed, 10 deselected** in 46.60s (no timeout).
- tests | High | tests/core/test_engine_auth.py:65 | `test_account_selection_requires_account_login` (3 of its parametrizations) fails with `KeyError: 'claude-account'` — the engine is missing from `settings.engines` in this fixture setup. | Add/restore the `claude-account` entry to the `TonySettings()` default engines used by this test, or update the fixture to construct it explicitly.
- tests | High | tests/core/test_engine_auth.py:40 | `test_account_credentials_are_isolated_from_api_environment` fails, consistent with the same missing `claude-account` engine configuration. | Same fix as above — align the test fixture with the current engine-auth settings shape.
- tests | Medium | tests/apps/web/test_api_engines.py:106 | `test_engine_api_lists_profiles_and_rejects_unknown` fails, likely downstream of the same engine-auth configuration gap. | Verify against the corrected `TonySettings()` engines fixture once the above is fixed.

These three failures sit in code already modified on the current branch (`feat/pluggable-engines`, engine-auth abstraction in progress) — pre-existing to this review, not introduced by the recent agent-folder-convention change.
