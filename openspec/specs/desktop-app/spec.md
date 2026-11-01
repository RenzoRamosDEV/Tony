# desktop-app Specification

## Purpose
Defines Tony's native desktop window: how it is launched, its Chat, Activity and Edith zones, the PIN dialog, and how the user interface exchanges events and commands with the core running in its own thread without ever being closed by a core failure.

## Requirements

### Requirement: Launch without subcommand
Running `tony` with no subcommand SHALL open the desktop window; any subcommand SHALL keep its terminal behaviour and `tony --help` SHALL still print the help.

#### Scenario: Bare command
- **WHEN** the user runs `uv run tony`
- **THEN** the desktop app starts and no help text is printed

#### Scenario: Subcommand unaffected
- **WHEN** the user runs `uv run tony audit`
- **THEN** the audit table is printed and no window opens

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
The Chat zone SHALL have a text input that sends the message on Enter, a reply-mode selector with `auto`, `voice`, `text`, `both` reflecting the current mode (updated by `reply_mode` events) and a microphone button driven by `voice_state`: disabled with a tooltip stating the reason while `loading` or `unavailable`, enabled while `ready` (click sends `listen`), and showing «Escuchando…» while `listening` (click sends `stop_listening`).

#### Scenario: Mode changed in the selector
- **WHEN** the user selects `text`
- **THEN** a `set_mode` command with mode `text` is sent

#### Scenario: Microphone placeholder
- **WHEN** the window opens and `voice_state` is `loading`
- **THEN** the microphone button is visible and disabled with a tooltip saying the voice models are loading

#### Scenario: Microphone unavailable
- **WHEN** a `voice_state` event `unavailable` with reason `voice extra not installed` arrives
- **THEN** the microphone button is disabled and its tooltip contains `voice extra not installed`

#### Scenario: Start and stop listening
- **WHEN** `voice_state` is `ready` and the user clicks the microphone, then `voice_state` `listening` arrives and the user clicks again
- **THEN** the commands `{"type": "listen"}` and `{"type": "stop_listening"}` are sent in that order

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

### Requirement: Edith audit view
The Edith panel SHALL list today's audit lines (local date) with time, agent, tool, verdict, rule and user decision, read once through the page channel when the page is ready and then appending each new `tool_call` event, filterable by verdict (all, `allow`, `confirm`, `deny`). The rows given to the page SHALL NOT contain tool arguments.

#### Scenario: Filter by verdict
- **WHEN** today's audit has one `allow` and one `deny` line and the user selects `deny`
- **THEN** only the `deny` line is listed

#### Scenario: No arguments in audit rows
- **WHEN** today's audit has a line for `filesystem.read_file` with arguments
- **THEN** the row given to the page has time, agent, tool, verdict, rule and user decision and no arguments

### Requirement: Core thread and command queue
The UI SHALL run in the Qt main thread and the core in a separate thread with its own asyncio loop. Core events SHALL reach the UI only as Qt signals, and the UI SHALL send only JSON commands through a queue: `send_message` {text, origin}, `confirm` {task_id, decision}, `cancel` {}, `set_mode` {mode}, `unlock` {pin}, `listen` {}, `stop_listening` {}. `origin` SHALL be `text` (default) or `voice`. The UI and the page MUST NOT call the core directly.

#### Scenario: Message round trip
- **WHEN** the UI sends `{"type": "send_message", "text": "Hola"}`
- **THEN** the core handles it in its own thread with origin `text` and the resulting events are delivered to the UI in the main thread

#### Scenario: Invalid command
- **WHEN** the queue receives `{"type": "fly"}`
- **THEN** an `error` event naming the command type is published and the core keeps processing commands

#### Scenario: Invalid origin
- **WHEN** the queue receives `{"type": "send_message", "text": "Hola", "origin": "telepathy"}`
- **THEN** an `error` event naming `send_message` and `origin` is published and no turn starts

#### Scenario: Listen without voice
- **WHEN** voice is `unavailable` and the core receives `{"type": "listen"}`
- **THEN** an `error` event with source `listen` naming the unavailability reason is published

### Requirement: Core failures never close the window
A failing MCP server, a model error or any exception raised while the core handles a command SHALL be published as an `error` event and shown in the Chat zone; the window and the core thread SHALL keep running.

#### Scenario: Exception in a handler
- **WHEN** handling a `send_message` command raises an unexpected exception
- **THEN** an `error` event is shown, the window stays open and the next message is answered

### Requirement: Cancel command
The `cancel` command SHALL stop the current front-agent turn, stop any speech being played and any listening session, and cancel any running delegated task with the reason `tarea cancelada por el usuario`, answering a pending confirmation as `deny`.

#### Scenario: Cancel during a task
- **WHEN** a delegated task is running and the user sends `cancel`
- **THEN** the task ends with outcome `cancelled` and its `errores` contains `tarea cancelada por el usuario`

#### Scenario: Cancel while listening
- **WHEN** the microphone is listening and the user sends `cancel`
- **THEN** the microphone is closed and `voice_state` `ready` is published

### Requirement: Close stops the core
Closing the window SHALL cancel any running turn and task, close all MCP connections and stop the core thread before the process exits.

#### Scenario: Close during a task
- **WHEN** the user closes the window while a task with a stdio MCP server is running
- **THEN** the server process has exited when the app exits

### Requirement: Chat follows the turn's write decision
On `turn_started` with `writes: false`, the chat SHALL NOT grow a bubble from that turn's `token` events and SHALL add the full reply as one bubble when the turn's `result` arrives. On `writes: true`, bubbles grow token by token as before.

#### Scenario: Speak-only turn
- **WHEN** `turn_started` with `writes: false`, two `token` events and the turn `result` with text `Buenas tardes, señor.` arrive for `jarvis`
- **THEN** no bubble exists before the `result`, and afterwards one Jarvis bubble shows `Buenas tardes, señor.`

### Requirement: Voice transcript in the chat
A `transcript` event SHALL add a user bubble with its text, labelled «Tú (voz)».

#### Scenario: Transcript bubble
- **WHEN** a `transcript` event with text `¿Qué hora es?` arrives
- **THEN** a user bubble labelled `Tú (voz)` with `¿Qué hora es?` is added

### Requirement: Embedded web front
The window's content SHALL be the built web front loaded from `tony/apps/desktop/web/dist/index.html` through a local file URL, rendered inside the native window. No HTTP or websocket server SHALL be started and no separate browser SHALL be opened.

#### Scenario: Built page loaded
- **WHEN** `tony/apps/desktop/web/dist/index.html` exists and the app starts
- **THEN** the window shows that page from a `file://` URL and no listening TCP port is opened by the app

### Requirement: Missing web build fallback
When `tony/apps/desktop/web/dist/index.html` does not exist, the window SHALL show a native message containing the command `npm --prefix tony/apps/desktop/web ci && npm --prefix tony/apps/desktop/web run build`, and the core, voice, tray, single instance, `tony --focus`, hotkey and notifications SHALL keep working.

#### Scenario: Missing build
- **WHEN** `tony/apps/desktop/web/dist/index.html` does not exist and the app starts
- **THEN** the window shows the build command, the core thread runs, `voice_state` events are still published and a second `tony` raises this window

### Requirement: Page sandbox
The page SHALL have every permission request denied (including microphone, camera, geolocation and notifications), SHALL NOT navigate away from its own `index.html`, SHALL NOT load remote resources, and SHALL open only `http` and `https` links in the system browser; links with any other scheme SHALL be ignored.

#### Scenario: Microphone requested by the page
- **WHEN** the page requests microphone access
- **THEN** the request is denied

#### Scenario: External link clicked
- **WHEN** the user clicks a link to `https://example.org/` in a reply
- **THEN** the system browser is asked to open it and the page stays on `index.html`

#### Scenario: Other navigation blocked
- **WHEN** the page tries to navigate to `file:///etc/passwd` or `javascript:alert(1)`
- **THEN** the navigation is blocked and nothing is opened externally

### Requirement: Page event channel
Every core event SHALL be delivered to the page as its JSON text, in publication order, once the page has announced it is ready. On that announcement the window SHALL first replay the latest `voice_state`, `reply_mode` and `auth` events, the latest `mcp_status` per agent and server, and the pending `needs_confirmation` if any. Events before the announcement SHALL NOT be queued otherwise.

#### Scenario: Event forwarded as JSON
- **WHEN** the page is ready and the core publishes `{"type": "token", "ts": "<ts>", "agent": "jarvis", "text": "Hola"}`
- **THEN** the page receives that object serialised as JSON, unchanged

#### Scenario: Late page catches up
- **WHEN** `voice_state` `loading`, `auth` `locked`/`start` and `mcp_status` for `filesystem` are published before the page announces it is ready
- **THEN** on the announcement the page receives those three events before any later event

#### Scenario: Answered confirmation not replayed
- **WHEN** a `needs_confirmation` for task `t1` was followed by a `tool_call` for `t1` and then the page announces it is ready
- **THEN** no `needs_confirmation` is replayed

### Requirement: Page command channel
The page SHALL send commands as JSON text through one channel. Each SHALL be decoded and validated with the core's command rules; `send_message`, `confirm`, `cancel`, `set_mode`, `unlock`, `listen` and `stop_listening` SHALL be forwarded to the core queue. Malformed JSON, an invalid command or `stop` SHALL NOT reach the core and SHALL produce an `error` event shown in the page that never echoes the submitted values.

#### Scenario: Valid command forwarded
- **WHEN** the page sends `{"type": "confirm", "task_id": "t1", "decision": "allow"}`
- **THEN** exactly that command reaches the core queue

#### Scenario: Stop refused
- **WHEN** the page sends `{"type": "stop"}`
- **THEN** nothing reaches the core queue, an `error` event naming `stop` is shown and the core keeps running

#### Scenario: Invalid unlock does not echo the PIN
- **WHEN** the page sends `{"type": "unlock", "pin": "1234", "extra": true}`
- **THEN** an `error` event naming `unlock` is shown, it does not contain `1234` and nothing reaches the core queue

#### Scenario: Malformed JSON
- **WHEN** the page sends `{"type":`
- **THEN** an `error` event is shown and nothing reaches the core queue

### Requirement: Web front layout
The page SHALL show the orb centred behind a chat panel, a text input, the microphone button, a reply-mode selector (`auto`, `voice`, `text`, `both`), a collapsible Activity panel and a collapsible Edith panel, in the visual style of the v1 front. Collapsing a panel MUST NOT discard its content. The page SHALL load no remote fonts or scripts.

#### Scenario: Layout present
- **WHEN** the page is rendered
- **THEN** it shows the orb stage, the chat panel with its input, the microphone button, the reply-mode selector and the Activity and Edith panels each with a collapse control

#### Scenario: Collapse keeps content
- **WHEN** the Activity panel shows a task and the user collapses and expands it
- **THEN** the task is still shown

### Requirement: Orb state
The orb SHALL show one state derived from events, with this priority: `confirming` while a confirmation is pending; `speaking` while `voice_level` events with source `output` keep arriving (none for 300 ms ends it); `listening` while `voice_state` is `listening`; `thinking` from `turn_started` or `task_started` until the first `token` of a turn with `writes: true`, the first output level, `result` with scope `turn` or `error` with source `front`; otherwise `idle`.

#### Scenario: Thinking then speaking
- **WHEN** `turn_started` with `writes: false`, two `token` events and then a `voice_level` with source `output` arrive
- **THEN** the orb state goes `idle`, `thinking` (kept through the tokens), `speaking`, and returns to `idle` 300 ms after the last output level

#### Scenario: Confirmation wins
- **WHEN** a `needs_confirmation` arrives while output levels are arriving
- **THEN** the orb state is `confirming` until the confirmation is answered or its task ends

#### Scenario: Listening
- **WHEN** `voice_state` `listening` arrives
- **THEN** the orb state is `listening` until `voice_state` `ready` arrives

### Requirement: Orb amplitude
The orb's amplitude SHALL follow the `level` of the latest `voice_level` event (0 to 1) while listening or speaking, smoothed with a fast attack and slow release, and SHALL decay to 0 when no level arrives. Level updates SHALL NOT re-render the chat or panels.

#### Scenario: Level drives the orb
- **WHEN** `voice_level` events with source `input` and level `0.8` arrive while listening
- **THEN** the orb amplitude rises towards `0.8` and falls to `0` after the levels stop

### Requirement: Orb fallback
When WebGL is unavailable or its context is lost, the page SHALL render the static orb fallback instead of the animated orb and SHALL keep the chat and panels working.

#### Scenario: No WebGL
- **WHEN** the page starts where WebGL cannot be created
- **THEN** the fallback orb is shown and a typed message is still sent

### Requirement: Confirmation card
A `needs_confirmation` event SHALL show a card with the question and the buttons «Permitir», «Denegar» and, only when the event has `allow_always: true`, «Permitir siempre», with keyboard focus on «Denegar». They SHALL send a `confirm` command with decision `allow`, `deny` or `always` for that task and hide the card. The card SHALL be hidden when the task ends or a `tool_call` for that task arrives.

#### Scenario: User allows
- **WHEN** the card for task `t1` is shown and the user clicks «Permitir»
- **THEN** the command `{"type": "confirm", "task_id": "t1", "decision": "allow"}` is sent, the card disappears and the orb leaves `confirming`

#### Scenario: Allow-always hidden for a tool with a deny rule
- **WHEN** a `needs_confirmation` event for `shell.run` with `allow_always: false` arrives
- **THEN** the card shows «Permitir» and «Denegar» and no «Permitir siempre» button

#### Scenario: Allow-always shown for a tool without a deny rule
- **WHEN** a `needs_confirmation` event for `filesystem.delete_file` with `allow_always: true` arrives
- **THEN** the «Permitir siempre» button is visible and enabled

#### Scenario: Default focus
- **WHEN** the card appears
- **THEN** «Denegar» has keyboard focus

### Requirement: PIN overlay
On an `auth` event that asks for the PIN (`start`, `idle`, `wrong_pin`, `backoff`) the page SHALL show an overlay with a hidden PIN field, a submit and a cancel button. During a back-off it SHALL disable input and count down `retry_in_s`. With reason `no_lock_file` it SHALL show only an explanation containing `tony pin set`. While locked the page SHALL offer an unlock control that reopens it.

#### Scenario: Back-off countdown
- **WHEN** an `auth` event with `reason: "wrong_pin"` and `retry_in_s: 10` arrives
- **THEN** the PIN field is disabled and shows the remaining seconds until it is enabled again

#### Scenario: Cancel
- **WHEN** the user cancels the overlay
- **THEN** the command `{"type": "unlock", "pin": null}` is sent

#### Scenario: Unlock control while locked
- **WHEN** an `auth` event with `state: "locked"` and `reason: "cancelled"` arrives and the user activates the unlock control
- **THEN** the overlay is shown again with the PIN field enabled

### Requirement: PIN never retained by the page
The PIN SHALL be sent once in an `unlock` command; the field SHALL be cleared immediately after sending, and the PIN SHALL NOT be kept in page state, browser storage or logs, nor ever sent back to the page.

#### Scenario: Field cleared after submit
- **WHEN** the user types `1234` and submits
- **THEN** exactly one `{"type": "unlock", "pin": "1234"}` is sent, the field is empty and no page state or storage contains `1234`

### Requirement: Web front build
The front SHALL build with `npm --prefix tony/apps/desktop/web ci && npm --prefix tony/apps/desktop/web run build` into `tony/apps/desktop/web/dist/`. `dist/` and `node_modules/` SHALL be gitignored, the built `dist/` SHALL be included in the installed package, and the README SHALL document the build. The default Python and frontend test runs SHALL NOT need a GPU or network.

#### Scenario: Ignored build output
- **WHEN** `.gitignore` is read
- **THEN** it ignores `tony/apps/desktop/web/dist/` and `node_modules/`

#### Scenario: README build section
- **WHEN** the README is read
- **THEN** it contains `npm --prefix tony/apps/desktop/web ci` and `npm --prefix tony/apps/desktop/web run build`
