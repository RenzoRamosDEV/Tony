# Spec Delta

## Purpose

Defines the structured task and result contract of worker agents, how a worker runs a task with its proxied tools, and the `tony run` command that exposes this from the CLI.

## ADDED Requirements

### Requirement: Structured task contract
A worker task SHALL be a JSON object `{objetivo, contexto, restricciones}` where `objetivo` is a non-empty string, `contexto` a string and `restricciones` a list of strings.

#### Scenario: Empty objective rejected
- **WHEN** a task is built with an empty `objetivo`
- **THEN** it is rejected before any agent runs

### Requirement: Structured result contract
A worker run SHALL produce a JSON object `{resumen, datos, pasos, errores}`: `resumen` string, `datos` any JSON value or `null`, `pasos` list of strings, `errores` list of strings.

#### Scenario: Unstructured model answer
- **WHEN** the model's final answer is not a valid structured result
- **THEN** the run returns a result whose `errores` states the answer was not structured and whose `resumen` carries the raw answer text

### Requirement: Worker execution with proxied tools
Running a worker SHALL connect its declared MCP servers, offer the model only its proxied tools, use the model id resolved from its alias and its `agent.md` body as system prompt, and send the task as the user message.

#### Scenario: Viernes uses two tools offline
- **WHEN** Viernes runs `Resume las notas de la carpeta` against the fake filesystem server holding `a.md` and the fake model is scripted to call `filesystem.list_directory` then `filesystem.read_file` and answer with a structured result
- **THEN** both calls execute against the server, `pasos` reflects both, and the result's `datos` includes content read from `a.md`

#### Scenario: Viernes uses two tools with the real model
- **WHEN** with `TONY_EVALS=1`, Viernes runs a task over a temporary folder served by `@modelcontextprotocol/server-filesystem`
- **THEN** the task log shows at least one `list_directory`-type call and one `read_file`-type call and the result is structured

### Requirement: Only worker agents run tasks
`tony run` SHALL only run agents whose role is `worker`.

#### Scenario: Running a non-worker
- **WHEN** the user runs `tony run jarvis "hola"` and `jarvis` has role `front`
- **THEN** the command exits non-zero with an error stating the agent is not a worker

### Requirement: Task timeout
A task SHALL be aborted after 300 seconds; the run SHALL return a result whose `errores` states the timeout, close all connections, and log `task_finished` with the timeout outcome.

#### Scenario: Task exceeds timeout
- **WHEN** a task is still running after 300 seconds
- **THEN** it is stopped and the result's `errores` contains a timeout message

### Requirement: Run command
`tony run <agent> "<task>"` SHALL build a task with the text as `objetivo`, empty `contexto` and empty `restricciones`, run it, print the result as JSON on stdout and exit 0 when the run produced a result with no `errores`, non-zero otherwise.

#### Scenario: Successful run
- **WHEN** the user runs `tony run viernes "Lista mis notas"` and the run succeeds
- **THEN** stdout is a single JSON object with keys `resumen`, `datos`, `pasos`, `errores` and the exit code is 0

#### Scenario: Unknown agent
- **WHEN** the user runs `tony run nadie "x"` and `agents/nadie/` does not exist
- **THEN** the command exits non-zero with an error naming the missing agent folder and prints no result

#### Scenario: Invalid agent definition
- **WHEN** the named agent's `agent.md` fails validation
- **THEN** the command exits non-zero and stderr contains the validation error naming the file and field
