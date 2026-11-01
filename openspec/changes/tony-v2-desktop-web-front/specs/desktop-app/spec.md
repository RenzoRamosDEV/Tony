# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Single window with three zones
**Reason**: The native Chat, Activity and Edith zones are replaced by the embedded web front.
**Migration**: See «Embedded web front» and «Web front layout»; the Activity and Edith panels are collapsible inside the page.

### Requirement: Edith confirmation banner
**Reason**: The native Edith banner is replaced by the confirmation card of the web front, shown over the orb.
**Migration**: See «Confirmation card»; the `confirm` command and its decisions are unchanged.

### Requirement: PIN dialog
**Reason**: The native PIN dialog and the «Desbloquear Edith» menu are replaced by the PIN overlay of the web front.
**Migration**: See «PIN overlay» and «PIN never retained by the page»; the `unlock` command is unchanged.
