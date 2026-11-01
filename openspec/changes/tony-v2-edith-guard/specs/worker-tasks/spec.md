# Spec Delta

## MODIFIED Requirements

### Requirement: Task timeout
A task SHALL be aborted after `limits.task_timeout_s` of the loaded policy (300 seconds by default), confirmation waits included; the run SHALL return a result whose `errores` states the timeout, close all connections, and log `task_finished` with the timeout outcome.

#### Scenario: Task exceeds timeout
- **WHEN** a task is still running after 300 seconds
- **THEN** it is stopped and the result's `errores` contains a timeout message

#### Scenario: Policy timeout applied
- **WHEN** the policy declares `limits: {task_timeout_s: 1}` and the worker hangs
- **THEN** the task is stopped after about 1 second with a timeout message in `errores`

### Requirement: Run command
`tony run <agent> "<task>"` SHALL build a task with the text as `objetivo`, empty `contexto` and empty `restricciones`, run it with Edith as guard and the terminal as confirmation channel, print the result as JSON on stdout and exit 0 when the run produced a result with no `errores`, non-zero otherwise.

#### Scenario: Successful run
- **WHEN** the user runs `tony run viernes "Lista mis notas"` and the run succeeds
- **THEN** stdout is a single JSON object with keys `resumen`, `datos`, `pasos`, `errores` and the exit code is 0

#### Scenario: Unknown agent
- **WHEN** the user runs `tony run nadie "x"` and `agents/nadie/` does not exist
- **THEN** the command exits non-zero with an error naming the missing agent folder and prints no result

#### Scenario: Invalid agent definition
- **WHEN** the named agent's `agent.md` fails validation
- **THEN** the command exits non-zero and stderr contains the validation error naming the file and field

#### Scenario: Confirmation answered on the terminal
- **WHEN** the user runs `tony run viernes "Borra notas/viejo.md"`, the worker calls `filesystem.delete_file` and the user types `s`
- **THEN** the question is printed on stderr, the file is deleted, and stdout is the JSON result

#### Scenario: Invalid policy
- **WHEN** `agents/edith/policy.yaml` fails validation
- **THEN** the command exits non-zero, stderr names the policy file and field, and no worker runs
