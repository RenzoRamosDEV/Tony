# chat-cli Specification

## Purpose
Defines the terminal commands for talking to the front agent (`tony chat`) and for listing the configured agents (`tony agents`).

## Requirements

### Requirement: Chat command
`tony chat` SHALL read one message per input line, send it to the front agent and print the streamed reply on stdout prefixed with the agent name in title case and `: ` (e.g. `Jarvis: `), ending with a newline. It SHALL exit 0 on end of input or the line `/salir`; empty lines SHALL be ignored.

#### Scenario: One exchange
- **WHEN** the user runs `tony chat`, types `Hola` and then ends the input, with the fake model answering `Buenas tardes, señor.`
- **THEN** stdout contains `Jarvis: Buenas tardes, señor.` and the exit code is 0

#### Scenario: Error does not end the chat
- **WHEN** the model fails on the first message and succeeds on the second
- **THEN** an error line prefixed `tony:` is printed on stderr and the second reply is printed

### Requirement: Chat confirmations
In `tony chat`, confirmations SHALL use the CLI confirmation channel with the question printed on stderr prefixed `Edith: `, and the answer SHALL be read from the same input stream as the messages without losing or stealing a later message line after a timeout.

#### Scenario: Confirmed delete in chat
- **WHEN** a delegated task calls `filesystem.delete_file` and the user types `s`
- **THEN** stderr shows `Edith: Acción: ` followed by the question and the tool runs

#### Scenario: Line after a timeout
- **WHEN** a confirmation times out and the user then types `Hola`
- **THEN** `Hola` is sent to the front agent as the next message

### Requirement: Chat PIN prompt
When the session starts locked with a valid lock file, `tony chat` SHALL ask the PIN with hidden input before the first message; an empty entry or end of input SHALL cancel into conversation-only mode. The line `/pin` SHALL ask the PIN again, and an idle relock SHALL ask it on the next `delegate`.

#### Scenario: Correct PIN at start
- **WHEN** `config/edith.lock` holds the hash of `4821` and the user types `4821` at the hidden prompt
- **THEN** the session is unlocked and delegated tasks run

#### Scenario: Empty PIN
- **WHEN** the user presses Enter at the PIN prompt
- **THEN** the chat continues in conversation-only mode

### Requirement: Agents command
`tony agents` SHALL print a table with columns `slot`, `agent`, `role`, `model`, `voice` with one row each for the `front`, `worker` and `guard` agents of `config/tony.yaml` (model shown as its alias) and exit 0; an invalid agent definition SHALL exit non-zero with the validation error on stderr.

#### Scenario: Default agents
- **WHEN** the user runs `tony agents` with the bundled agents
- **THEN** the output has a header and the rows `front jarvis front claude-haiku kokoro/em_alex`, `worker viernes worker claude-sonnet kokoro/em_alex` and `guard edith guard claude-haiku kokoro/ef_dora` (columns separated by spaces)

#### Scenario: Invalid agent
- **WHEN** `agents/jarvis/agent.md` declares `role: helper`
- **THEN** the command exits non-zero and stderr names the file and the field `role`
