# Proposal

## Why

Tony v2 can already run Viernes on a structured task under Edith's policy, but only through `tony run`: there is no conversational agent, no memory, no session authentication and no desktop window. This change adds Jarvis as the front agent that talks to the user and delegates work to Viernes, plus the PySide6 window that is the main way of using Tony (voice arrives in a later change).

## What Changes

- Bundled `agents/jarvis/` (role `front`, model `claude-haiku`, voice `kokoro/em_alex`, formal and ironic British-butler persona that addresses the user as «señor») with an empty `tool.json`; Viernes persona updated (close, agile, pragmatic, subtle humour only inside `resumen`).
- Orchestrator: the only component that knows the three agents, resolved by the `front`, `worker` and `guard` slots of `config/tony.yaml` (setting `front: viernes` makes Viernes the conversational agent). The front agent gets exactly three control tools, `delegate`, `remember` and `set_reply_mode`, plus the MCP tools its own `tool.json` declares. `delegate({objetivo, contexto, restricciones})` runs a worker task and returns its `{resumen, datos, pasos, errores}` to the front agent; the worker never writes to the user. A short waiting phrase is emitted once if a delegated task has no result after 3 s.
- Core events (JSON): `token`, `progress`, `task_started`, `tool_call` (with verdict), `needs_confirmation`, `result`, `token_alert`, `mcp_status`, `error`, plus `auth` and `reply_mode`; `audio_chunk` is reserved for the voice change.
- Memory: `memory/preferences.md` injected into the front agent's prompt (`remember` appends `- <text>`); conversation history in `memory/conversations.sqlite`, the last 20 messages of the current conversation sent as history.
- Reply mode `auto|voice|text|both`: set from the UI selector or by phrase (`set_reply_mode`, persisted as `reply_mode: <mode>` in `preferences.md`), or for one message with the `/v` or `/t` prefix (stripped). Stored only; voice output arrives later.
- Edith PIN: `tony pin set` stores an argon2 hash in `config/edith.lock`; PIN requested at start with 10/30/60 s back-off after 3 failures; cancelling or a missing lock file with `pin_required: true` enters conversation-only mode (`delegate` returns `{"error": "locked"}`); idle relock after `lock_after_min` minutes, PIN requested on the next `delegate`.
- CLI: `tony chat` (text conversation, `Edith:`-prefixed confirmations, hidden PIN input), `tony agents` (the three agents with role, model and voice), `tony pin set`. **BREAKING**: `tony` with no subcommand launches the desktop app instead of printing help.
- Desktop app (PySide6): one window with Chat (coloured bubbles per agent, token streaming, Markdown rendered with `markdown-it-py`, mode selector, disabled microphone placeholder), Activity (tasks, tool calls with verdict, subagents as children, tokens, elapsed time, MCP servers with a red marker when down) and Edith (pending-confirmation banner with «Permitir», «Denegar», «Permitir siempre»; today's audit filterable by verdict). Core runs in its own thread and asyncio loop; events reach the UI as Qt signals; the UI sends JSON commands through a queue; core failures never close the window.
- «Permitir siempre» inserts `{match: "<tool id>", verdict: allow, id: "user-always/<tool id>"}` at the top of the guard's `policy.yaml` rules and allows the pending call. It is offered only when no `deny` rule pattern of the current policy matches the tool id (ignoring `when`), so it can never override a deny rule.
- Confirmation port receives a JSON confirmation request (`task_id`, `tool`, `args_preview`, `question`, `allow_always`) instead of a bare question string.
- Phase-02 leftover: stdio MCP servers' stderr written to `logs/mcp/<server>.log` is passed through the task's secret masker.

## Capabilities

### New Capabilities
- `front-conversation`: front-agent turns, role-slot resolution, the `delegate`/`remember`/`set_reply_mode` control tools, waiting phrase and reply mode.
- `conversation-memory`: `memory/preferences.md` and the `memory/conversations.sqlite` history.
- `core-events`: the JSON event types the core emits and their fields.
- `edith-session`: PIN storage, unlock with back-off, conversation-only mode, idle relock and `tony pin set`.
- `chat-cli`: `tony chat` and `tony agents`.
- `desktop-app`: the PySide6 window, its three zones, the core thread/command-queue bridge and failure isolation.

### Modified Capabilities
- `agent-definitions`: Viernes persona changes; bundled Jarvis agent added.
- `tool-proxy`: front control tools are offered to the front agent and are not judged by the guard.
- `guard-confirmation`: confirmation requests carry task id, tool and args preview; CLI channel prefix in `tony chat`; desktop channel.
- `guard-policy`: «Permitir siempre» eligibility (no matching deny rule) and rule insertion into `policy.yaml`.
- `mcp-connections`: masked stdio stderr log; server status published.
- `task-supervision`: user-initiated task cancellation.

## Impact

- New code: `tony/core/orchestrator/{conversation,front_tools,runtime}.py`, `tony/core/memory/{preferences,history}.py`, `tony/core/guard/{pin,session,broker,allow_always}.py`, `tony/core/events/core_events.py`, `tony/apps/desktop/` (presenters, widgets, bridge).
- Modified code: `tony/core/orchestrator/{runner,proxy,claude_engine,ports}.py`, `tony/core/mcp/manager.py`, `tony/core/guard/{confirm,edith}.py`, `tony/apps/cli/main.py`.
- New data: `agents/jarvis/agent.md`, `agents/jarvis/tool/tool.json`; runtime files `memory/preferences.md`, `memory/conversations.sqlite`, `config/edith.lock` (all gitignored).
- Dependencies: `pyside6`, `argon2-cffi`, `markdown-it-py`; dev `pytest-qt`.
- Out of scope: voice input/output, tray, single instance, hotkey, notifications, skills, subagent execution, hot reload, packaging.
