# Design

## Context

- `run_task` (`tony/core/orchestrator/runner.py`) runs one worker task per call: loads config, agent and policy, builds `EdithGuard`, `TaskSupervisor`, `JsonlTaskLog`, opens a per-task `McpManager`, races the engine against cancellation and timeout. It has no way to publish events to a UI or to be cancelled from outside.
- `ToolProxy` logs `tool_call` before judging; the verdict is only visible in `logs/audit.jsonl`.
- `ModelEngine.run` (`ClaudeEngine`) is one-shot with a JSON-schema `output_format`; there is no streaming and no conversation.
- `Confirmer.ask(question: str)`; `CliConfirmer` reads stdin in a daemon thread per question (a late answer after a timeout is consumed by that orphan thread).
- `McpManager._transport` passes a plain file object as `errlog`; the `mcp` SDK hands it to the subprocess as its stderr fd, so output bypasses Python and the masker.
- `policy.auth` (`pin_required`, `lock_after_min`) is parsed but unused; `tony/core/memory/` and `tony/apps/desktop/` are empty packages.
- Constraints: offline default tests with fakes; real-model tests marked `evals`; JSON-serializable messages; Qt confined to `tony/apps/desktop/`.

## Goals / Non-Goals

**Goals:**
- One Qt-free conversation core shared by `tony chat` and the desktop app.
- Qt-free presenters holding all UI logic; widgets only render presenter state and forward user actions.
- Reuse `run_task` for delegation unchanged in behaviour, extended only with event publishing and external cancellation.

**Non-Goals:**
- Long-lived MCP connections (connections stay per task/turn; the start probe connects and closes).
- Applying `reply_mode` to output (no voice yet), tray, notifications, single instance, hotkey.
- Hot reload of `policy.yaml` (allow-always reaches later tasks because each task loads the policy).
- Preserving YAML comments when rewriting `policy.yaml` (see Risks).

## Decisions

### D1. Module layout (Ports and Adapters)

```
tony/core/events/core_events.py     builders for UI events (+ts), Publisher type, MaskingPublisher
tony/core/memory/preferences.py      PreferencesFile: read, append_line, reply_mode get/set
tony/core/memory/history.py          HistoryStore (stdlib sqlite3): add, recent(conversation_id, 20)
tony/core/guard/pin.py               PinStore: set/verify argon2 hash in config/edith.lock
tony/core/guard/session.py           EdithSession: lock state, failures, back-off, idle (pure, injected clock)
tony/core/guard/broker.py            ConfirmationBroker: desktop Confirmer (queue + futures + allow-always)
tony/core/guard/allow_always.py      offers_allow_always(policy, tool); insert_allow_always(root, guard, tool) -> atomic rewrite
tony/core/guard/confirm.py           ConfirmationRequest; Confirmer.ask(request); CliConfirmer(read_line, prefix)
tony/core/orchestrator/agents.py     resolve_slots(config) -> front/worker/guard definitions
tony/core/orchestrator/front_tools.py  delegate/remember/set_reply_mode as ProxiedTool handlers
tony/core/orchestrator/conversation.py Conversation: one front-agent turn (prefix, history, prefs, engine)
tony/core/orchestrator/runtime.py    CoreRuntime: command loop, session gate, MCP probe, error isolation
tony/core/orchestrator/{ports,claude_engine,runner,proxy}.py   extended (ChatEngine, publish, cancel)
tony/core/mcp/{manager,stderr}.py    status callback; MaskedStderr pipe
tony/apps/cli/main.py                chat, agents, pin set, desktop launch on bare `tony`
tony/apps/desktop/presenters/*.py    chat, activity, edith, pin, markdown (Qt-free)
tony/apps/desktop/bridge.py          CoreThread + QtEventBridge(Signal(object))
tony/apps/desktop/widgets/*.py, app.py   PySide6 widgets and launch()
```
- Alternative rejected: Qt models (`QAbstractItemModel`) as the UI state. They would force every UI test through Qt; plain presenters are tested with pytest and mutated.

### D2. Conversational engine port

- New `ChatEngine` protocol: `converse(spec, system_prompt, prompt, tools, model_id, on_text) -> ChatOutcome(text, usage)`. `ClaudeEngine` implements it next to `run`, sharing `build_options` (no `output_format`, `include_partial_messages=True`); `StreamEvent` `content_block_delta`/`text_delta` chunks call `on_text`; the final text comes from `ResultMessage.result`.
- History goes in the user prompt as a delimited transcript (`<historial>` lines `usuario:`/`<agent>:`, then `<mensaje>`), one stateless SDK session per turn. Alternative rejected: SDK session resume — state would live in the SDK instead of `memory/conversations.sqlite` and the 20-message window could not be enforced.
- System prompt = `agent.md` body + `\n\n## Preferencias del usuario\n` + masked `preferences.md` (re-read every turn; cheapest way to honour manual edits).
- `FakeChatEngine` (tests/fakes) scripts text chunks, control-tool calls and errors.

### D3. Front control tools

- Exposed as `ProxiedTool`s with ids `tony.delegate`, `tony.remember`, `tony.set_reply_mode` (SDK names `mcp__tony__*`), merged with the front agent's own proxied catalog; `make_can_use_tool` receives the merged id set, so a worker requesting them is denied.
- They are not wrapped by `ToolProxy`: no guard, no audit (spec tool-proxy "Front control tools bypass the guard"). The names are not in `NATIVE_TOOLS`, so `"native": ["delegate"]` in a `tool.json` still fails as unknown.
- Alternative rejected: route them through Edith. The shipped policy (fixed content, `default: confirm`) would ask the user to confirm every delegation and every remembered preference.
- `delegate`: validate `TaskRequest` → `session_gate.ensure_unlocked()` (`{"error": "locked"}` on failure) → `run_task(worker, request, deps)` as an asyncio task → `asyncio.wait(timeout=3.0)`; if pending, publish one `progress` with `WAITING_PHRASE = "Un momento, señor; estoy en ello."` → await → return `result.model_dump_json()`.

### D4. Runner extensions

- `RunDeps` gains `publish: Publisher` (default no-op) and `user_cancel: asyncio.Event | None`. `_race` also waits on `user_cancel`; when set, `supervisor.cancel("tarea cancelada por el usuario")`.
- `run_task` publishes `task_started`, `result` (scope `task`, outcome, tokens, `elapsed_ms` from `monotonic`); the supervisor's sink becomes a tee that writes the log and publishes `token_alert` with `task_id`.
- `ToolProxy` gets `publish`; after `guard.decide` it publishes `tool_call` with `args_preview(args, masker)` (reused from `audit.py`) and the ruling.
- `McpManager` gets `on_status(server, ServerStatus)`; the runner adapts it to `mcp_status` with the agent name.
- All publishing goes through `MaskingPublisher(masker)`; the guard `args_preview` additionally masks secret-looking keys.

### D5. Confirmation port and channels

- `ConfirmationRequest(task_id, tool, args_preview, question, allow_always)` pydantic model; `Confirmer.ask(request) -> bool | None`. `EdithGuard._ask_user` builds it, computing `allow_always = offers_allow_always(policy, tool)` (the guard already holds the policy); `CliConfirmer` prints `f"{prefix}{request.question} "`.
- `CliConfirmer(read_line: Callable[[], Awaitable[str | None]], prefix="")`; the default `read_line` keeps today's daemon-thread stdin read (for `tony run`). `tony chat` uses `ConsoleLines`: one daemon thread feeding an `asyncio.Queue`; both the REPL and the confirmer `await queue.get()`. On timeout, `wait_for` cancels the `get()` so the next line goes to the REPL — this is what makes "Line after a timeout" hold.
- `ConfirmationBroker` (desktop): an `asyncio.Lock` serialises requests; `ask` checks `always_allowed` (set of tool ids, per runtime) → `True` without publishing; otherwise publishes `needs_confirmation`, stores `(task_id, future)` and awaits. `answer(task_id, decision)` resolves only a matching pending future; `always` on a request with `allow_always: true` first calls `insert_allow_always` (errors → `error` event) and adds the tool to `always_allowed`; on a request with `allow_always: false` it is treated as `allow` (once, nothing written) — defence in depth against a stale or forged command. `cancel(task_id)` resolves `False`.

### D6. Allow-always eligibility and rewrite

- `offers_allow_always(policy, tool) = not any(r.verdict == deny and any(fnmatchcase(tool, p) for p in r.patterns) for r in policy.rules)`; `when` is deliberately ignored, so a tool that is denied under any condition can never get a blanket allow rule placed above its deny rule.
- Alternative rejected: offering the button everywhere with a warning tooltip — an allow rule at the top would silently override `deny` rules such as `shell.run/deny`.
- `yaml.safe_load` → reject if a rule with id `user-always/<tool>` exists (no-op) → `rules.insert(0, {...})` → `Policy.model_validate` → `yaml.safe_dump(sort_keys=False, allow_unicode=True)` to a temp file in the same folder → `os.replace`.
- Alternative rejected: `ruamel.yaml` to keep comments — new dependency for a cosmetic property the spec does not require.

### D7. Edith session and PIN

- `PinStore`: `argon2.PasswordHasher()` defaults; file written via temp + `os.replace` with mode `0600`; `verify` maps `VerifyMismatchError` → `False`, `InvalidHashError`/missing file → "no valid lock".
- `EdithSession` (pure): states `unlocked`, `locked(reason)`, `conversation_only`; `attempt(pin)` returns an `AuthState(state, reason, retry_in_s)`; back-off table `wait_after(failures) = 0 (<3), 10 (3), 30 (4), 60 (≥5)` against an injected `monotonic`; `touch()` on each user message applies idle relock (`>= lock_after_min * 60`).
- `SessionGate.ensure_unlocked()` used by `delegate`: unlocked → True; conversation-only → False; idle-locked → `PinPrompt.request()` loop until success, cancel or `confirm_timeout_s`.
- `PinPrompt` adapters: desktop = publish `auth` and await the next `unlock` command (future in the runtime); CLI = `getpass` in a thread. The PIN only lives in the `unlock` command object and the verify call; the runtime never logs commands and error messages never include command payloads.

### D8. Memory

- `PreferencesFile`: `read()`, `append_line(text)` (normalise whitespace, mask, `- ` prefix), `reply_mode()` (last valid `reply_mode:` line), `set_reply_mode(mode)` (replace all such lines with one, else append).
- `HistoryStore`: stdlib `sqlite3`, one connection owned by the core thread, table `messages(id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT, agent TEXT, content TEXT, ts TEXT)` + index on `(conversation_id, id)`. `recent(cid, 20)` = `ORDER BY id DESC LIMIT 20` reversed. Conversation id = `uuid4().hex` per app/chat start.
- Alternative rejected: a history across conversations. It mixes stale context from earlier days into every prompt; durable facts belong in `preferences.md`.

### D9. Core runtime (desktop) and threading

```
Qt main thread                           core thread (asyncio loop)
 widgets -> presenters                    CoreRuntime
   | user action -> command dict            commands: asyncio.Queue
   +-- CoreThread.submit(cmd) ---call_soon_threadsafe--> queue.put_nowait
                                            dispatch: send_message | confirm | cancel | set_mode | unlock
 QtEventBridge.event(Signal(object)) <--emit-- publish(event)   (Qt queues cross-thread emits)
   -> presenters.apply(event) -> widgets.render()
```
- Commands validated with a pydantic discriminated union; unknown/invalid → `error` event. Each handler runs inside `try/except Exception` → `error` event (source = command type). `send_message` turns run one at a time (queued); `cancel` cancels the current turn task, sets `user_cancel` and calls `broker.cancel`.
- Start: resolve slots (failure → `error` event, window stays open with input disabled), init session (publish `auth`), publish `reply_mode`, start the MCP probe as a background task (open `McpManager` for front and worker, close).
- Stop (window close): submit `stop` → cancel turn and probe, close history → `loop.stop()`; `CoreThread.join(5)`.
- Alternative rejected: `qasync` (single loop shared with Qt). It ties the core to Qt and contradicts the separate-thread requirement.

### D10. Desktop presenters and widgets

- `MarkdownRenderer`: `MarkdownIt("commonmark", {"html": False}).enable("table")`.
- `ChatPresenter`: list of bubbles `{agent, label, colour, markdown, html}`; consecutive `token`s of the same agent append to the open bubble; `result` scope `turn` closes it; `error` adds a system bubble. Colours: `jarvis #2F6FED`, `viernes #2E9E5B`, `edith #E0A100`, others `#6B7280`.
- `ActivityPresenter`: tasks by `task_id`; `tool_call` nodes grouped under `agent` path segments (`viernes/resumidor` → child node); `result` adds tokens and elapsed; `mcp_status` keyed by `(agent, server)`.
- `EdithPresenter`: pending request (one) with `offers_always` from the event's `allow_always`, audit rows (initial load through the read-only `read_audit`/`select_lines` file functions for the local date, then appended from `tool_call` events), verdict filter. Reading the audit file is a read-only file access, not a core call.
- `PinPresenter`: dialog mode (`prompt`, `explain`, hidden), countdown from `retry_in_s` with injected clock.
- Widgets (`MainWindow`, `ChatView` with `QTextBrowser` bubbles, `ActivityPanel` with `QTreeWidget`, `EdithPanel`, `PinDialog`, collapsible `QGroupBox`es) subscribe to presenter changes and call `submit`.

### D11. CLI

- `create_app(..., chat_engine_factory, desktop_launcher, getpass, console_factory)`; the callback uses `invoke_without_command=True` and calls `desktop_launcher()` when no subcommand is given (PySide6 imported lazily inside `tony.apps.desktop.app.launch`). `no_args_is_help` removed; `--help` unaffected.
- `tony chat`: `Conversation` + `CliConfirmer(prefix="Edith: ")` + CLI `PinPrompt`; token events printed as they arrive; `/salir`, `/pin`.
- `tony agents`: `resolve_slots` + table formatter shared with `audit_table`.
- `tony pin set`: typer sub-app `pin` with command `set`.

### D12. Masked stdio stderr

- `MaskedStderr(path, masker)` context manager: `os.pipe()`; the write end as a text file object is the `errlog`; a daemon thread reads the read end line by line, writes `masker.mask(line)` to `logs/mcp/<server>.log` and flushes. Entered on the server's `AsyncExitStack` *before* the transport so it closes after the process: closing the parent's write end gives EOF once the child exits; the thread is joined (2 s cap).
- Alternative rejected: post-processing the log file after the task — secrets would sit unmasked on disk while the task runs.

### D13. Testing strategy

- Pure units (pytest): presenters, markdown, session/back-off, pin store, preferences, history (tmp sqlite), allow-always rewrite, broker, front tools, conversation with `FakeChatEngine` + `FakeModelEngine` + fake fs server, runtime with fakes (no Qt), CLI with `CliRunner` and injected factories.
- Qt: `pytest-qt` (`qt_api = "pyside6"`), `QT_QPA_PLATFORM=offscreen` set in `tests/conftest.py`; tests for widget rendering/actions and the bridge (`qtbot.waitSignal` for cross-thread delivery, fake runtime).
- Golden file for the event sequence of a delegated task (`tests/golden/events_delegate.jsonl`, `ts` normalised).
- `evals`: one real-model test where Jarvis delegates a listing and answers in Spanish.
- Mutation: presenters, core modules and CLI mutated; `tony/apps/desktop/widgets/` and `tony/apps/desktop/app.py` in `do_not_mutate` (pure Qt layout/glue: behaviour lives in presenters, and mutating widget calls mostly yields equivalent or crash-only mutants under offscreen Qt); the live SDK streaming branch is covered by the fake client.

## Risks / Trade-offs

- [A user-always rule is broader than the confirmation that created it (any args)] → Only offered for tools with no `deny` rule, so it never overrides a deny; README documents removing `user-always/*` rules.
- [Rewriting `policy.yaml` with PyYAML drops comments] → README states it; rule order and all keys are preserved and validated before an atomic replace.
- [A secret split across two streamed `token` chunks is not masked] → The front agent never receives secrets (tool results, preferences and history are masked), so it can only echo what the user typed.
- [Start probe spawns each stdio server once (e.g. `npx` ~1–2 s)] → Runs in the background; connections closed immediately.
- [`memory/conversations.sqlite` grows without bound] → Small text rows; pruning deferred.
- [Idle relock measured between user messages, not between key presses] → Matches "without user input" at message granularity; documented.
- [Waiting phrase says «señor» even with `front: viernes`] → Accepted; a per-agent phrase can be added later without spec changes to the timing.
- [PySide6 adds ~200 MB to the environment] → Required by the chosen UI toolkit.

## Migration Plan

- `uv add pyside6 argon2-cffi markdown-it-py` and `uv add --dev pytest-qt`.
- **BREAKING**: bare `tony` now opens the window; scripts must call subcommands explicitly (`tony --help` unchanged).
- Users run `tony pin set` once; until then the app is conversation-only (`pin_required: true` in the shipped policy).
- Rollback: revert the change's commits; runtime files (`memory/*`, `config/edith.lock`) are gitignored and ignored by earlier code.
