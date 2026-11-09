# Spec Delta

## Purpose

Runs user-defined prompts on a daily schedule as guarded worker tasks while Tony is running, recording every occurrence so none runs twice.

## ADDED Requirements

### Requirement: Routine definition
A routine SHALL have a name, a prompt, a time `HH:MM`, a weekday set (default every day), an IANA timezone (default the system zone, `UTC` when unknown) and an enabled flag. `routines add` SHALL reject an invalid time, weekday, timezone or empty prompt with the usage error code.

#### Scenario: Add with defaults
- **WHEN** the user runs `tony routines add mañana --time 08:30 --prompt "resume mis tareas"`
- **THEN** the routine is stored enabled for every weekday and its id is printed

#### Scenario: Invalid timezone
- **WHEN** `--tz Mars/Base` is given
- **THEN** a usage error names the timezone and nothing is stored

#### Scenario: Invalid time
- **WHEN** `--time 25:00` is given
- **THEN** a usage error is printed and nothing is stored

### Requirement: Routine management commands
`tony routines list` SHALL print id, name, time, weekdays, timezone and enabled state. `remove ID` SHALL delete the routine, `enable ID` and `disable ID` SHALL toggle it. An unknown id SHALL exit with the usage error code.

#### Scenario: Disable stops scheduling
- **WHEN** a routine is disabled
- **THEN** it creates no new occurrences

#### Scenario: Enable does not backfill
- **WHEN** a routine is enabled after its time of day has already passed
- **THEN** that day's earlier occurrence is not run

#### Scenario: Unknown id
- **WHEN** `tony routines remove 99` names no routine
- **THEN** a usage error is printed

### Requirement: Occurrence identity
Each occurrence SHALL be identified as `<routine_id>:<YYYY-MM-DD>:<HH:MM>` using the routine's configured local date and time in its timezone, and an occurrence id SHALL be recorded at most once.

#### Scenario: Same occurrence seen twice
- **WHEN** the scheduler checks the same due occurrence in two ticks or two processes
- **THEN** exactly one run record and one task exist

#### Scenario: Ambiguous local time
- **WHEN** a clock change makes the local time occur twice on a date
- **THEN** the routine runs once for that date

#### Scenario: Nonexistent local time
- **WHEN** a clock change skips the configured local time on a date
- **THEN** the routine runs once for that date, shortly after the change

### Requirement: Scheduler cadence and weekdays
While running, the scheduler SHALL check every 30 seconds and treat an enabled routine's occurrence as due once its local time has passed on a selected weekday. Occurrences before the routine was added or last enabled SHALL be ignored.

#### Scenario: Due on a selected weekday
- **WHEN** it is Monday 08:31 in the routine's zone and the routine is Monday 08:30
- **THEN** the occurrence is recorded and run

#### Scenario: Unselected weekday
- **WHEN** it is Tuesday 08:31 and the routine selects only Monday
- **THEN** nothing is recorded

### Requirement: Missed occurrences
A due occurrence not yet recorded SHALL run when it is at most 12 hours late and SHALL be stored with status `skipped` when it is later. A queued occurrence that becomes more than 12 hours late before running SHALL be marked `skipped`.

#### Scenario: Late by one hour
- **WHEN** Tony starts one hour after a routine's time
- **THEN** the occurrence runs

#### Scenario: Late by thirteen hours
- **WHEN** Tony starts 13 hours after a routine's time
- **THEN** the occurrence is stored `skipped` and no task runs

### Requirement: Locked session queues runs
While the guard session is locked, due occurrences SHALL stay `queued` and no task SHALL start; after unlock they SHALL run in due order within the 12 hour limit. The scheduler MUST NOT prompt for the PIN.

#### Scenario: Locked at due time
- **WHEN** an occurrence is due while the session is locked
- **THEN** its status is `queued` and no task starts

#### Scenario: Unlock releases the queue
- **WHEN** the session unlocks and the occurrence is under 12 hours late
- **THEN** the task runs and the status becomes `ok` or `error`

### Requirement: Routine runs are guarded worker tasks
A routine run SHALL execute its prompt as the objective of a worker task with origin `routine` under the same guard, limits, journal and confirmations as any task. Confirmations nobody answers SHALL be denied by the existing confirmation timeout; scheduling MUST NOT authorise any action.

#### Scenario: Confirmation unanswered
- **WHEN** a routine task calls a tool requiring confirmation and nobody answers
- **THEN** the call is not executed after the confirmation timeout

#### Scenario: Policy unchanged
- **WHEN** a routine task calls a tool the policy denies
- **THEN** it is denied exactly as for a user task

### Requirement: Run records and inbox
Each occurrence SHALL have a run record with started time, status `queued`, `ok`, `error` or `skipped`, and a masked result text capped at 2000 characters. `tony routines inbox [--limit N]` SHALL print runs newest first (default 20) with routine name, occurrence, status and the first line of the result.

#### Scenario: Successful run
- **WHEN** a routine task finishes without errors
- **THEN** the run is `ok` and the inbox shows the summary

#### Scenario: Failed run
- **WHEN** the task ends with errors, cancellation or timeout
- **THEN** the run is `error` and the result holds the error text

#### Scenario: Removed routine
- **WHEN** a routine is removed
- **THEN** its past runs still appear in the inbox

#### Scenario: Crash during a run
- **WHEN** a run has been started for more than 10 minutes and is still unfinished
- **THEN** it is marked `error` with text `interrupted` and is not run again

### Requirement: Routines run only while Tony runs
Routines SHALL NOT run when neither `tony chat` nor the desktop runtime is running; `tony routines` commands SHALL only edit definitions and read records.

#### Scenario: Command without runtime
- **WHEN** `tony routines add` runs while no runtime is active
- **THEN** the definition is stored and no task starts
