# core-events Specification

## Purpose
Defines the JSON events the core publishes to the user interfaces (desktop window and terminal chat) while conversing, running delegated tasks and asking for confirmations.

## Requirements

### Requirement: Event envelope
Every core event SHALL be a JSON object with `type` and `ts` (UTC ISO 8601) plus the type's fields, SHALL round-trip through JSON unchanged and MUST NOT contain secret values or the PIN.

#### Scenario: Round trip
- **WHEN** any event is published
- **THEN** `json.loads(json.dumps(event)) == event` and it contains `type` and `ts`

#### Scenario: Secret in a tool argument
- **WHEN** a `tool_call` event is built for args containing the value of a variable defined in `config/.env`
- **THEN** its `args_preview` contains `***` instead of the value

### Requirement: Conversation event types
For the conversation and session the core SHALL publish: `token` {agent, text}; `progress` {agent, text}; `result` (see Result events); `error` {source, message}; `auth` {state, reason, retry_in_s}; `reply_mode` {mode}; `turn_started` {agent, origin, reply_mode, speaks, writes}; `transcript` {text}; `voice_state` {state, reason}. The type `audio_chunk` stays reserved and MUST NOT be published: audio never leaves the core.

#### Scenario: Token event fields
- **WHEN** Jarvis streams the text `Hola`
- **THEN** the event is `{"type": "token", "ts": "<ts>", "agent": "jarvis", "text": "Hola"}`

#### Scenario: Turn started fields
- **WHEN** the user says «Hola» with reply mode `auto` and voice ready
- **THEN** before any `token` of that turn the event `{"type": "turn_started", "ts": "<ts>", "agent": "jarvis", "origin": "voice", "reply_mode": "auto", "speaks": true, "writes": false}` is published

#### Scenario: No audio events
- **WHEN** a reply is spoken
- **THEN** no event of type `audio_chunk` is published

### Requirement: Task event types
For delegated tasks and tools the core SHALL publish: `task_started` {task_id, agent, objetivo}; `tool_call` {task_id, agent, tool, args_preview, verdict, rule, user_decision}; `needs_confirmation` {task_id, tool, args_preview, question, allow_always}; `token_alert` {task_id, total_tokens, limit}; `mcp_status` {agent, server, up, reason}.

#### Scenario: Delegated task event order
- **WHEN** Jarvis delegates a task in which Viernes calls `filesystem.read_file` once and succeeds
- **THEN** the events include, in order, `task_started`, `mcp_status` for `filesystem` with `up: true`, `tool_call` with `verdict: "allow"` and `rule: "filesystem.read_*/allow"`, and `result` with scope `task`, followed later by the front agent's `token` events and `result` with scope `turn`

### Requirement: Tool call event carries the verdict
A `tool_call` event SHALL be published after the guard's ruling for every judged call, including denied and unconfirmed calls, with `verdict`, `rule` and `user_decision` equal to the audit line's values. A call stopped by the step limit before judging SHALL publish none.

#### Scenario: Denied call
- **WHEN** Viernes calls `shell.run` with `command="sudo dnf update"` under the shipped policy
- **THEN** a `tool_call` event with `verdict: "deny"`, `rule: "shell.run/deny"` and `user_decision: null` is published

### Requirement: Result events
A `result` event with scope `task` SHALL be published when a delegated task ends, with `task_id`, `agent`, `outcome` (`ok`, `error`, `timeout`, `cancelled`), `result` (the task result), `input_tokens`, `output_tokens` and `elapsed_ms`. A `result` event with scope `turn` SHALL be published when a front-agent reply completes, with `agent`, `text` and `reply_mode` (the mode applied to that message).

#### Scenario: Cancelled task result
- **WHEN** a delegated task is cancelled because the user denied a confirmation
- **THEN** a `result` event with scope `task`, `outcome: "cancelled"` and the cancellation reason in `result.errores` is published

### Requirement: Auth event
An `auth` event SHALL be published whenever the Edith session state changes or an unlock attempt is rejected, with `state` (`locked` or `unlocked`), `reason` (`start`, `no_lock_file`, `wrong_pin`, `backoff`, `idle`, `cancelled`, `unlocked` or `not_required`) and `retry_in_s` (whole seconds before the next attempt is accepted, `0` when none).

#### Scenario: Third failure
- **WHEN** the third wrong PIN is entered
- **THEN** an `auth` event with `state: "locked"`, `reason: "wrong_pin"` and `retry_in_s: 10` is published

### Requirement: Voice state event
A `voice_state` event SHALL be published whenever the voice state changes, with `state` one of `loading`, `ready`, `listening`, `unavailable` and `reason` (a text for `unavailable`, otherwise `null`).

#### Scenario: Listening and back
- **WHEN** voice is ready and a listening session starts and ends with an utterance
- **THEN** `voice_state` events with `state` `listening` and then `ready` (both with `reason: null`) are published

### Requirement: Voice level event
While a listening session captures audio or synthesised speech is playing, the core SHALL publish `voice_level` {source, level} about every 50 ms: `source` is `input` (microphone) or `output` (speech), `level` is the RMS of the latest audio divided by 0.2, clamped to 0..1 and rounded to two decimals. No `voice_level` SHALL be published otherwise. It carries numbers only, never audio samples.

#### Scenario: Levels while listening
- **WHEN** a listening session captures 1 s of audio
- **THEN** between 15 and 25 `voice_level` events with `source: "input"` and a `level` between 0 and 1 are published

#### Scenario: Levels while speaking
- **WHEN** a sentence of 1 s is played
- **THEN** `voice_level` events with `source: "output"` are published while it plays and none after it ends or is stopped

#### Scenario: Silent when idle
- **WHEN** voice is `ready` and neither listening nor playing
- **THEN** no `voice_level` event is published

#### Scenario: Level fields
- **WHEN** the latest microphone window has an RMS of 0.05
- **THEN** the event is `{"type": "voice_level", "ts": "<ts>", "source": "input", "level": 0.25}`
