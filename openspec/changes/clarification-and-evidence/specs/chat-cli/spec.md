## ADDED Requirements

### Requirement: Chat clarifications
In `tony chat` and `tony run`, a clarification SHALL print the question on stderr prefixed with the asking agent's name in title case and `: ` (e.g. `Viernes: `), then one numbered line `<n>) <option>` per option, and read one answer line from the same input stream as the messages, without stealing a later message line after a timeout.

#### Scenario: Question and options printed
- **WHEN** Viernes asks "¿Qué cuenta uso?" with options `personal` and `trabajo`
- **THEN** stderr shows `Viernes: ¿Qué cuenta uso?`, `1) personal` and `2) trabajo`

#### Scenario: Line after a timeout
- **WHEN** a clarification times out and the user then types `Hola`
- **THEN** `Hola` is sent to the front agent as the next message

### Requirement: Clarification answer parsing
With options, an answer line that is an integer from 1 to the number of options SHALL select that option's text; any other non-blank line SHALL be the answer as typed. A blank line or end of input SHALL mean no answer.

#### Scenario: Number selects an option
- **WHEN** the options are `personal` and `trabajo` and the user types `2`
- **THEN** the answer is `trabajo`

#### Scenario: Free text accepted
- **WHEN** the user types `la de la oficina`
- **THEN** the answer is `la de la oficina`

#### Scenario: Out-of-range number is text
- **WHEN** the user types `7` with two options
- **THEN** the answer is `7`

#### Scenario: Blank line
- **WHEN** the user presses Enter without typing
- **THEN** the worker receives the error `no answer from the user`

### Requirement: Chat shows sources
`tony chat` SHALL print the `Fuentes:` list of the answer-evidence capability after a delegated task result that holds sources.

#### Scenario: Listed after result
- **WHEN** a delegated task returns one verified source `gmail · Factura`
- **THEN** stdout contains `Fuentes:` followed by `- gmail · Factura`
