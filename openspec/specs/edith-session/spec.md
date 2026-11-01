# edith-session Specification

## Purpose
Defines Edith's session authentication: the PIN stored as an argon2 hash, how the session is unlocked with back-off after failures, the conversation-only mode in which delegation is refused, and the idle relock.

## Requirements

### Requirement: PIN set command
`tony pin set` SHALL ask for the PIN twice with hidden input and, when both entries are equal and at least 4 characters long, write its argon2 hash to `config/edith.lock` (replacing any previous one, file mode `0600`) and exit 0. A mismatch or a shorter PIN SHALL exit non-zero and leave the file unchanged.

#### Scenario: PIN stored as hash
- **WHEN** the user runs `tony pin set` and types `4821` twice
- **THEN** `config/edith.lock` exists, starts with `$argon2`, does not contain `4821`, and the exit code is 0

#### Scenario: Entries differ
- **WHEN** the user types `4821` and then `4822`
- **THEN** the command exits non-zero and `config/edith.lock` is unchanged

#### Scenario: PIN too short
- **WHEN** the user types `123` twice
- **THEN** the command exits non-zero stating the minimum length

### Requirement: PIN never in clear
The PIN MUST NOT be written in clear to any file, log, event, audit line, error message or terminal output.

#### Scenario: Wrong PIN logged nowhere
- **WHEN** the user enters the wrong PIN `9999`
- **THEN** no file under `logs/` or `memory/` and no published event contains `9999`

### Requirement: Session state at start
At start, the session SHALL be unlocked without asking when the guard policy has `auth.pin_required: false`. Otherwise it SHALL be locked: with a valid `config/edith.lock` the PIN is requested (`auth` reason `start`); with no lock file, or one that is not a valid argon2 hash, it enters conversation-only mode (reason `no_lock_file`) and the user is told to run `tony pin set`.

#### Scenario: PIN not required
- **WHEN** the policy has `auth: {pin_required: false}`
- **THEN** no PIN is asked and `delegate` runs tasks

#### Scenario: No lock file
- **WHEN** `pin_required` is `true` and `config/edith.lock` does not exist
- **THEN** the session is in conversation-only mode and the message shown contains `tony pin set`

### Requirement: Unlock with back-off
A correct PIN SHALL unlock the session and reset the failure count. After the 3rd consecutive wrong PIN the next attempt SHALL be accepted only after 10 s, after the 4th after 30 s, and after the 5th and each further failure after 60 s. An attempt during the wait SHALL be rejected without checking the PIN and without counting as a failure.

#### Scenario: Back-off sequence
- **WHEN** the user enters a wrong PIN five times, each as soon as allowed
- **THEN** the waits after failures 1 to 5 are 0, 0, 10, 30 and 60 seconds

#### Scenario: Attempt during the wait
- **WHEN** 4 s after the third failure the user enters the correct PIN
- **THEN** it is rejected with `reason: "backoff"` and `retry_in_s: 6`, and the session stays locked

#### Scenario: Correct PIN resets
- **WHEN** after two failures the correct PIN is entered
- **THEN** the session is unlocked and the next wrong PIN after a relock counts as the first failure

### Requirement: Conversation-only mode
Cancelling the PIN prompt SHALL put the session in conversation-only mode: the front agent keeps answering, `delegate` returns `{"error": "locked"}` without asking for the PIN, and the user can unlock later on request (desktop unlock action, `/pin` in `tony chat`).

#### Scenario: Cancelled prompt
- **WHEN** the user cancels the PIN dialog and asks Jarvis to list the notes
- **THEN** Jarvis answers, `delegate` returns `{"error": "locked"}` and no task log is created

### Requirement: Idle relock
When the session is unlocked and a user message arrives `auth.lock_after_min` minutes or more after the previous user message, the session SHALL lock with reason `idle`. The PIN SHALL then be requested on the next `delegate`, which waits for it up to `limits.confirm_timeout_s`; a correct PIN runs the task, a cancel or timeout returns `{"error": "locked"}`.

#### Scenario: Relock after 30 minutes
- **WHEN** with the default policy the user writes 31 minutes after the previous message and Jarvis calls `delegate`
- **THEN** the PIN is requested before any task is created, and the task runs only after the correct PIN

#### Scenario: Activity keeps the session open
- **WHEN** the user writes every 10 minutes for an hour
- **THEN** the session never relocks
