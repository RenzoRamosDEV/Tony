# Spec Delta

## Purpose

Defines the JSON events the core publishes to the user interfaces (desktop window and terminal chat) while conversing, running delegated tasks and asking for confirmations.

## ADDED Requirements

### Requirement: Event envelope
Every core event SHALL be a JSON object with `type` and `ts` (UTC ISO 8601) plus the type's fields, SHALL round-trip through JSON unchanged and MUST NOT contain secret values or the PIN.

#### Scenario: Round trip
- **WHEN** any event is published
- **THEN** `json.loads(json.dumps(event)) == event` and it contains `type` and `ts`

#### Scenario: Secret in a tool argument
- **WHEN** a `tool_call` event is built for args containing the value of a variable defined in `config/.env`
- **THEN** its `args_preview` contains `***` instead of the value

### Requirement: Conversation event types
For the conversation and session the core SHALL publish: `token` {agent, text}; `progress` {agent, text}; `result` (see Result events); `error` {source, message}; `auth` {state, reason, retry_in_s}; `reply_mode` {mode}. The type `audio_chunk` is reserved and MUST NOT be published in this change.

#### Scenario: Token event fields
- **WHEN** Jarvis streams the text `Hola`
- **THEN** the event is `{"type": "token", "ts": "<ts>", "agent": "jarvis", "text": "Hola"}`

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
