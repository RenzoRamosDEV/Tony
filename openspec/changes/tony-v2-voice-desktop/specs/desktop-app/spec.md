# Spec Delta

## MODIFIED Requirements

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

### Requirement: Core thread and command queue
The UI SHALL run in the Qt main thread and the core in a separate thread with its own asyncio loop. Core events SHALL reach the UI only as Qt signals, and the UI SHALL send only JSON commands through a queue: `send_message` {text, origin}, `confirm` {task_id, decision}, `cancel` {}, `set_mode` {mode}, `unlock` {pin}, `listen` {}, `stop_listening` {}. `origin` SHALL be `text` (default) or `voice`. The UI MUST NOT call the core directly.

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

### Requirement: Cancel command
The `cancel` command SHALL stop the current front-agent turn, stop any speech being played and any listening session, and cancel any running delegated task with the reason `tarea cancelada por el usuario`, answering a pending confirmation as `deny`.

#### Scenario: Cancel during a task
- **WHEN** a delegated task is running and the user sends `cancel`
- **THEN** the task ends with outcome `cancelled` and its `errores` contains `tarea cancelada por el usuario`

#### Scenario: Cancel while listening
- **WHEN** the microphone is listening and the user sends `cancel`
- **THEN** the microphone is closed and `voice_state` `ready` is published

## ADDED Requirements

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
