# Spec Delta

## ADDED Requirements

### Requirement: Motor efectivo del `worker` determina la implementación

La ejecución de una tarea del `worker` SHALL usar la implementación de `AgentRunner` correspondiente al motor efectivo del agente (`claude_sdk`, `codex_cli` o un perfil `litellm`), manteniendo sin cambios el contrato `TaskRequest`/`TaskResult`, la barrera única de ejecución de tools y la secuencia de eventos de progreso, cualquiera que sea el motor.

#### Scenario: Worker con motor `codex_cli`
- **WHEN** el `worker` tiene `engine: codex_cli` y recibe una tarea
- **THEN** la tarea se ejecuta con la implementación de `codex_cli` y el `TaskResult` devuelto tiene la misma forma que con `claude_sdk`

#### Scenario: Eventos de progreso iguales entre motores
- **WHEN** la misma tarea se ejecuta una vez con `engine: claude_sdk` y otra con `engine: litellm`
- **THEN** ambas ejecuciones emiten `task.started`, `tool.call`, `tool.result` y `task.finished` en el mismo orden y con los mismos campos
