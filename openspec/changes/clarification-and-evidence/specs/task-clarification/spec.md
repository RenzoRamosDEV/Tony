## ADDED Requirements

### Requirement: Ask-user native tool
The native tool `tony.ask_user` SHALL take `{question: string, options?: string[]}` and return the user's answer as text. It SHALL be offered only to agents that declare it; a blank `question` or an `options` value that is not a list of strings SHALL return an error result and ask nothing.

#### Scenario: Answer returned to the worker
- **WHEN** Viernes calls `tony.ask_user` with `{"question": "¿Qué cuenta uso?", "options": ["personal", "trabajo"]}` and the user answers `trabajo`
- **THEN** the tool result is the text `trabajo` and the same task continues without restarting

#### Scenario: Blank question refused
- **WHEN** a worker calls `tony.ask_user` with `{"question": "  "}`
- **THEN** it receives an error result and no clarification is requested

### Requirement: Clarification request event
When `tony.ask_user` is called, the core SHALL publish `clarification_requested` {request_id, task_id, agent, question, options} and wait for the matching answer. `request_id` SHALL be unique per request and `options` SHALL be an empty list when none were given. The event MUST NOT be a `needs_confirmation` event.

#### Scenario: Event published
- **WHEN** task `t1` of agent `viernes` asks "¿Qué cuenta uso?" with options `["personal", "trabajo"]`
- **THEN** one `clarification_requested` event with those question and options, `task_id` `t1` and `agent` `viernes` is published and no `needs_confirmation` event is

### Requirement: Answer clarification command
The core command `{"type": "answer_clarification", "request_id": string, "answer": string}` SHALL resolve the pending clarification with that `request_id`. An answer whose `request_id` does not match the pending request, or that arrives when none is pending, SHALL be ignored. A `confirm` command MUST NOT resolve a clarification and an `answer_clarification` MUST NOT resolve a confirmation.

#### Scenario: Matching answer
- **WHEN** a clarification `r1` is pending and `answer_clarification` with `request_id` `r1` and answer `trabajo` arrives
- **THEN** the waiting `tony.ask_user` call returns `trabajo`

#### Scenario: Blank answer is no answer
- **WHEN** the answer text is empty or only whitespace
- **THEN** `tony.ask_user` returns the error `no answer from the user`

#### Scenario: Stale or unknown id ignored
- **WHEN** `answer_clarification` arrives with a `request_id` that is not the pending one
- **THEN** the pending clarification stays unresolved

#### Scenario: Confirm is not an answer
- **WHEN** a clarification is pending and a `confirm` command with `decision` `allow` arrives for its task
- **THEN** the clarification stays unresolved

### Requirement: Clarification wait is bounded
The wait for an answer SHALL last at most `confirm_timeout_s` of the Edith policy limits. On timeout, on task cancellation, or when no channel can ask (a run without an interactive host), `tony.ask_user` SHALL return the error result `no answer from the user`, and the pending request SHALL be discarded so a late answer is ignored.

#### Scenario: Timeout
- **WHEN** `confirm_timeout_s` is 60 and nobody answers within 60 s
- **THEN** `tony.ask_user` returns the error `no answer from the user` and the task is not cancelled by this wait

#### Scenario: Cancelled task
- **WHEN** the user cancels the task while a clarification is pending
- **THEN** `tony.ask_user` returns the error `no answer from the user` and the request is discarded

#### Scenario: No interactive channel
- **WHEN** a task asks a question in a run with no clarification channel
- **THEN** `tony.ask_user` immediately returns the error `no answer from the user`

### Requirement: One clarification at a time
The core SHALL ask at most one clarification at a time; a second request SHALL wait until the first is answered, timed out or cancelled.

#### Scenario: Serialised requests
- **WHEN** two `tony.ask_user` calls are made concurrently
- **THEN** the second `clarification_requested` is published only after the first request has ended

### Requirement: Clarification never authorises
The answer to a clarification SHALL be returned to the worker as data only. The call to `tony.ask_user` and its answer MUST NOT grant any permission, skip a confirmation or the PIN, nor change what the guard decides for any other call.

#### Scenario: Next call still judged
- **WHEN** the user answers a clarification and the worker then calls a tool whose rule is `confirm`
- **THEN** the guard still asks for confirmation before the tool runs

### Requirement: Ask-user call is guarded and audited
Every `tony.ask_user` call SHALL go through the tool proxy and the guard like any other tool call, be judged under the shipped policy with verdict `allow`, produce a `tool_call` event and one audit line, and count as a step of the agent. The per-call tool timeout MUST NOT apply to it; its wait is bounded as stated above.

#### Scenario: Judged and not timed by the tool timeout
- **WHEN** `tool_timeout_s` is 20, `confirm_timeout_s` is 60 and the user answers after 30 s
- **THEN** the call returns the answer and a `tool_call` event with verdict `allow` was published
