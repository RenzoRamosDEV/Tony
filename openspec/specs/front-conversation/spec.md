# front-conversation Specification

## Purpose
Defines how the conversational front agent answers the user, how the orchestrator resolves the front, worker and guard agents, and the control tools the front agent uses to delegate work, remember preferences and change the reply mode.

## Requirements

### Requirement: Agents resolved by configuration slot
The orchestrator SHALL be the only component that knows the three agents and SHALL resolve them from the `front`, `worker` and `guard` keys of `config/tony.yaml`. The front slot MUST NOT name a `guard` agent and the worker slot MUST name a `worker` agent; otherwise startup fails with an error naming `config/tony.yaml` and the key.

#### Scenario: Default slots
- **WHEN** the configuration is the default
- **THEN** Jarvis is the conversational agent, Viernes runs delegated tasks and Edith is the guard

#### Scenario: Viernes as front agent
- **WHEN** `config/tony.yaml` sets `front: viernes`
- **THEN** user messages are answered by Viernes, which is offered the front control tools in addition to its own MCP tools

#### Scenario: Guard in the front slot
- **WHEN** `config/tony.yaml` sets `front: edith`
- **THEN** startup fails with an error naming `config/tony.yaml` and the field `front`

### Requirement: Front agent turn
Each user message SHALL be answered by the front agent with the model resolved from its alias, a system prompt made of its `agent.md` body followed by the content of `memory/preferences.md`, the conversation history and the message as the current user input. The reply SHALL be streamed as `token` events and end with one `result` event of scope `turn`.

#### Scenario: Streamed reply
- **WHEN** the user writes `Hola` and the fake model streams `Buenas` and ` tardes, señor.`
- **THEN** two `token` events with agent `jarvis` and those texts are emitted, followed by a `result` event with scope `turn` and text `Buenas tardes, señor.`

#### Scenario: Model error does not end the session
- **WHEN** the model raises an error during a turn
- **THEN** an `error` event with source `front` is emitted, no assistant message is stored, and the next user message is answered normally

### Requirement: Front control tools
The front agent SHALL be offered exactly the control tools `delegate`, `remember` and `set_reply_mode`, plus the proxied tools of the MCP servers and native tools declared in its own `tool.json`. Worker agents MUST NOT be offered the control tools.

#### Scenario: Bundled Jarvis tools
- **WHEN** Jarvis answers a message with the bundled configuration
- **THEN** the model is offered exactly `delegate`, `remember` and `set_reply_mode`

#### Scenario: Worker never gets control tools
- **WHEN** Viernes runs a delegated task
- **THEN** none of `delegate`, `remember` or `set_reply_mode` is offered to it

### Requirement: Delegate runs a worker task
`delegate({objetivo, contexto, restricciones})` SHALL validate the arguments as a worker task, run it on the worker agent with the guard and the active confirmation channel, and return the task result `{resumen, datos, pasos, errores}` as JSON to the front agent. Invalid arguments SHALL return an error result without creating a task. The worker MUST NOT emit `token` events or write to the user.

#### Scenario: Delegated listing
- **WHEN** Jarvis calls `delegate` with `{"objetivo": "Lista mis notas", "contexto": "", "restricciones": []}` and the fake worker returns `{"resumen": "Hay 2 notas", "datos": ["a.md", "b.md"], "pasos": ["listar"], "errores": []}`
- **THEN** Jarvis receives exactly that JSON as the tool result and a task log exists for the new task

#### Scenario: Empty objective
- **WHEN** Jarvis calls `delegate` with `{"objetivo": ""}`
- **THEN** it receives an error result stating `objetivo` must not be empty and no task is created

### Requirement: Delegate is refused while locked
When the Edith session is locked, `delegate` SHALL return `{"error": "locked"}` and MUST NOT create a task, start the worker or connect any MCP server.

#### Scenario: Locked session
- **WHEN** the user cancelled the PIN dialog and Jarvis calls `delegate`
- **THEN** it gets `{"error": "locked"}` and no worker task is created

### Requirement: Waiting phrase
If a delegated task has produced no result 3 seconds after it started, exactly one `progress` event SHALL be emitted with the front agent's name and a text chosen at random from a fixed set of 50 distinct Spanish waiting phrases (which includes `Un momento, señor; estoy en ello.`), never the same phrase as the previous one. A task finishing within 3 seconds SHALL emit none.

#### Scenario: Slow task
- **WHEN** a delegated task takes 5 seconds
- **THEN** exactly one `progress` event whose text is one of the 50 waiting phrases is emitted before the task's `result` event

#### Scenario: Fast task
- **WHEN** a delegated task finishes in 1 second
- **THEN** no `progress` event is emitted

### Requirement: Remember tool
`remember({text})` SHALL append the line `- <text>` to `memory/preferences.md`, creating the folder and file when missing, with line breaks in `text` replaced by spaces, surrounding whitespace trimmed and secret values masked. An empty text SHALL return an error result and write nothing.

#### Scenario: Preference remembered
- **WHEN** Jarvis calls `remember` with `{"text": "Prefiero respuestas cortas"}`
- **THEN** `memory/preferences.md` ends with the line `- Prefiero respuestas cortas`

#### Scenario: Multi-line text
- **WHEN** Jarvis calls `remember` with `{"text": " uno\ndos "}`
- **THEN** the appended line is `- uno dos`

#### Scenario: Empty text
- **WHEN** Jarvis calls `remember` with `{"text": "   "}`
- **THEN** it receives an error result and the file is unchanged

### Requirement: Reply mode
The reply mode SHALL be one of `auto`, `voice`, `text`, `both`. Its initial value SHALL be the last `reply_mode: <mode>` line of `memory/preferences.md` when present and valid, otherwise `reply_mode` from `config/tony.yaml`. Changing it from the UI or with `set_reply_mode({mode})` SHALL persist it and emit a `reply_mode` event. The mode applied to a message SHALL decide whether its reply is spoken and written (see voice-conversation).

#### Scenario: Mode set by phrase
- **WHEN** the user says `contéstame solo por texto` and Jarvis calls `set_reply_mode` with `{"mode": "text"}`
- **THEN** `memory/preferences.md` contains exactly one `reply_mode:` line, `reply_mode: text`, and a `reply_mode` event with mode `text` is emitted

#### Scenario: Mode replaced, not duplicated
- **WHEN** `preferences.md` contains `reply_mode: text` and the mode is set to `both`
- **THEN** that line becomes `reply_mode: both` and the other lines are unchanged

#### Scenario: Invalid mode
- **WHEN** Jarvis calls `set_reply_mode` with `{"mode": "loud"}`
- **THEN** it receives an error result listing the valid modes and nothing is written

#### Scenario: Initial mode from preferences
- **WHEN** `config/tony.yaml` has `reply_mode: auto` and `preferences.md` contains `reply_mode: voice`
- **THEN** the initial reply mode is `voice`

#### Scenario: Mode fixed for the turn
- **WHEN** a turn starts in `voice` and Jarvis calls `set_reply_mode` with `{"mode": "text"}` during it
- **THEN** that turn keeps speaking and the next message applies `text`

### Requirement: One-message mode prefix
A user message starting with `/v` or `/t` followed by a space or the end of the text SHALL use `voice` or `text` respectively for that message only; the prefix and the following space SHALL be stripped before the message reaches the front agent and the history. The persisted mode MUST NOT change.

#### Scenario: Text prefix
- **WHEN** the persisted mode is `voice` and the user writes `/t ¿qué hora es?`
- **THEN** the front agent receives `¿qué hora es?`, that turn's `result` event has `reply_mode: text`, and the persisted mode is still `voice`

#### Scenario: Not a prefix
- **WHEN** the user writes `/verdad`
- **THEN** the message is sent unchanged and the persisted mode applies

### Requirement: Turn start announced
Each front-agent turn SHALL publish, before its first `token`, one `turn_started` event with the front agent's name, the message origin (`text` or `voice`), the applied reply mode and the resulting `speaks` and `writes`. `token` events SHALL still be published for every turn.

#### Scenario: Typed message
- **WHEN** the user types `Hola` with persisted mode `both` and voice ready
- **THEN** `turn_started` has `origin: "text"`, `reply_mode: "both"`, `speaks: true`, `writes: true`, followed by the turn's `token` events

#### Scenario: Terminal chat
- **WHEN** `tony chat` answers a message with persisted mode `voice`
- **THEN** the turn has `speaks: false` and `writes: true` and the reply is printed
