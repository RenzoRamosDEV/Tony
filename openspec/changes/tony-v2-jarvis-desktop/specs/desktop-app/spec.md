# Spec Delta

## Purpose

Defines Tony's native desktop window: how it is launched, its Chat, Activity and Edith zones, the PIN dialog, and how the user interface exchanges events and commands with the core running in its own thread without ever being closed by a core failure.

## ADDED Requirements

### Requirement: Launch without subcommand
Running `tony` with no subcommand SHALL open the desktop window; any subcommand SHALL keep its terminal behaviour and `tony --help` SHALL still print the help.

#### Scenario: Bare command
- **WHEN** the user runs `uv run tony`
- **THEN** the desktop app starts and no help text is printed

#### Scenario: Subcommand unaffected
- **WHEN** the user runs `uv run tony audit`
- **THEN** the audit table is printed and no window opens

### Requirement: Single window with three zones
The app SHALL show one window with a Chat zone, a collapsible Activity zone and a collapsible Edith zone. Collapsing a zone MUST NOT discard its content.

#### Scenario: Zones present
- **WHEN** the window opens
- **THEN** it shows the Chat zone and the Activity and Edith zones, each with a collapse control

### Requirement: Chat bubbles per agent
Each message SHALL be a bubble labelled with the agent name and coloured by agent: Jarvis `#2F6FED`, Viernes `#2E9E5B`, Edith `#E0A100`; user messages and other agents SHALL use a neutral colour. Agent replies SHALL grow token by token as `token` events arrive and be rendered from Markdown to HTML (CommonMark plus tables, raw HTML escaped).

#### Scenario: Streaming bubble
- **WHEN** `token` events `Buenas` and ` **tardes**` arrive for `jarvis`
- **THEN** one Jarvis bubble labelled `Jarvis` with colour `#2F6FED` shows `Buenas <strong>tardes</strong>`

#### Scenario: Code block and table
- **WHEN** a reply contains a fenced code block and a pipe table
- **THEN** the bubble HTML contains a `<pre><code>` element and a `<table>` element

#### Scenario: Raw HTML escaped
- **WHEN** a reply contains `<script>alert(1)</script>`
- **THEN** the bubble HTML contains `&lt;script&gt;` and no `<script>` element

### Requirement: Chat input controls
The Chat zone SHALL have a text input that sends the message on Enter, a reply-mode selector with `auto`, `voice`, `text`, `both` reflecting the current mode (updated by `reply_mode` events) and a microphone button that is disabled with a tooltip stating voice is not available yet.

#### Scenario: Mode changed in the selector
- **WHEN** the user selects `text`
- **THEN** a `set_mode` command with mode `text` is sent

#### Scenario: Microphone placeholder
- **WHEN** the window opens
- **THEN** the microphone button is visible and disabled

### Requirement: Activity zone
The Activity zone SHALL show the current task with its agent and objective, each tool call as a child with tool id and verdict (and user decision when present), calls of an agent named `<agent>/<subagent>` grouped as a child node of that subagent, the task's tokens and elapsed time once finished, and each MCP server with its state, marked red when down.

#### Scenario: MCP down at start
- **WHEN** the worker's `tool.json` declares a stdio server whose command does not exist alongside a working server, and the app starts
- **THEN** the broken server is shown marked red, the working server's tools are usable by delegated tasks and the window stays open

#### Scenario: Tool call with verdict
- **WHEN** a `tool_call` event with tool `filesystem.read_file` and verdict `allow` arrives for the current task
- **THEN** the task node shows a child `filesystem.read_file — allow`

### Requirement: MCP status probe at start
At start the core SHALL connect each MCP server declared by the front and worker agents, publish one `mcp_status` event per server and close the connections, without blocking the window or conversation.

#### Scenario: Probe events
- **WHEN** the app starts with the bundled agents
- **THEN** one `mcp_status` event for server `filesystem` of agent `viernes` is published

### Requirement: Edith confirmation banner
A `needs_confirmation` event SHALL show a banner in the Edith zone with the question and the buttons «Permitir», «Denegar» and, only when the event has `allow_always: true`, «Permitir siempre»; they send a `confirm` command with decision `allow`, `deny` or `always` for that task and hide the banner. When the event has `allow_always: false` the «Permitir siempre» button SHALL be hidden. The banner SHALL be hidden when the task ends.

#### Scenario: User allows
- **WHEN** the banner for task `t1` is shown and the user clicks «Permitir»
- **THEN** the command `{"type": "confirm", "task_id": "t1", "decision": "allow"}` is sent and the banner disappears

#### Scenario: Allow-always hidden for a tool with a deny rule
- **WHEN** a `needs_confirmation` event for `shell.run` with `allow_always: false` arrives
- **THEN** the banner shows «Permitir» and «Denegar» and the «Permitir siempre» button is not visible

#### Scenario: Allow-always shown for a tool without a deny rule
- **WHEN** a `needs_confirmation` event for `filesystem.delete_file` with `allow_always: true` arrives
- **THEN** the «Permitir siempre» button is visible and enabled

### Requirement: Edith audit view
The Edith zone SHALL list today's audit lines (local date) with time, agent, tool, verdict, rule and user decision, appending each new `tool_call` event, filterable by verdict (all, `allow`, `confirm`, `deny`).

#### Scenario: Filter by verdict
- **WHEN** today's audit has one `allow` and one `deny` line and the user selects `deny`
- **THEN** only the `deny` line is listed

### Requirement: PIN dialog
On an `auth` event that asks for the PIN, the app SHALL show a modal dialog with a hidden PIN field and a cancel button. During a back-off it SHALL disable input and count down `retry_in_s`. With reason `no_lock_file` it SHALL show only an explanation containing `tony pin set`. The window SHALL offer an unlock action while locked.

#### Scenario: Back-off countdown
- **WHEN** an `auth` event with `reason: "wrong_pin"` and `retry_in_s: 10` arrives
- **THEN** the PIN field is disabled and shows the remaining seconds until it is enabled again

#### Scenario: Cancel
- **WHEN** the user cancels the dialog
- **THEN** the command `{"type": "unlock", "pin": null}` is sent

### Requirement: Core thread and command queue
The UI SHALL run in the Qt main thread and the core in a separate thread with its own asyncio loop. Core events SHALL reach the UI only as Qt signals, and the UI SHALL send only JSON commands through a queue: `send_message` {text}, `confirm` {task_id, decision}, `cancel` {}, `set_mode` {mode}, `unlock` {pin}. The UI MUST NOT call the core directly.

#### Scenario: Message round trip
- **WHEN** the UI sends `{"type": "send_message", "text": "Hola"}`
- **THEN** the core handles it in its own thread and the resulting events are delivered to the UI in the main thread

#### Scenario: Invalid command
- **WHEN** the queue receives `{"type": "fly"}`
- **THEN** an `error` event naming the command type is published and the core keeps processing commands

### Requirement: Core failures never close the window
A failing MCP server, a model error or any exception raised while the core handles a command SHALL be published as an `error` event and shown in the Chat zone; the window and the core thread SHALL keep running.

#### Scenario: Exception in a handler
- **WHEN** handling a `send_message` command raises an unexpected exception
- **THEN** an `error` event is shown, the window stays open and the next message is answered

### Requirement: Cancel command
The `cancel` command SHALL stop the current front-agent turn and cancel any running delegated task with the reason `tarea cancelada por el usuario`, answering a pending confirmation as `deny`.

#### Scenario: Cancel during a task
- **WHEN** a delegated task is running and the user sends `cancel`
- **THEN** the task ends with outcome `cancelled` and its `errores` contains `tarea cancelada por el usuario`

### Requirement: Close stops the core
Closing the window SHALL cancel any running turn and task, close all MCP connections and stop the core thread before the process exits.

#### Scenario: Close during a task
- **WHEN** the user closes the window while a task with a stdio MCP server is running
- **THEN** the server process has exited when the app exits
