# Spec Delta

## Purpose

Define cómo Tony encola, ejecuta y supervisa las tareas que el agente `front` delega en el `worker`: ciclo de vida, límites de concurrencia, eventos observables, cancelación externa, timeout de tarea y entrega del resultado.

## ADDED Requirements

### Requirement: Resolución de agentes por rol
El orquestador SHALL ser el único componente que conoce a los dos agentes, y SHALL identificarlos únicamente por rol (`front` y `worker`) según la configuración global, nunca por nombre fijo en el código.

#### Scenario: Worker resuelto por configuración
- **GIVEN** `worker: viernes` en la configuración global
- **WHEN** el orquestador ejecuta una tarea
- **THEN** la ejecuta con el agente cargado desde `agents/viernes`

#### Scenario: Advertencia por rol discrepante
- **GIVEN** `worker: jarvis` y `agents/jarvis/agent.md` con `role: front`
- **WHEN** el orquestador prepara al `worker`
- **THEN** emite una advertencia que nombra al agente y los dos roles, y continúa sin error

### Requirement: Envío de tareas y cola
`submit(request, parent_id=None)` SHALL devolver una tarea en estado `queued` con un identificador único. SHALL haber como máximo una tarea raíz en ejecución a la vez y como máximo 10 tareas en `queued`; la 11.ª SHALL rechazarse con el error `queue_full` sin crear la tarea.

#### Scenario: Una tarea raíz activa
- **GIVEN** la tarea `t1` en `running`
- **WHEN** se envía `t2`
- **THEN** `t2` queda en `queued` y no empieza hasta que `t1` alcanza un estado final

#### Scenario: Orden de la cola
- **GIVEN** `t1` en `running` y `t2`, `t3` en `queued` en ese orden
- **WHEN** `t1` termina
- **THEN** `t2` pasa a `running` antes que `t3`

#### Scenario: Cola llena
- **GIVEN** una tarea en `running` y 10 tareas en `queued`
- **WHEN** se envía otra tarea
- **THEN** `submit` falla con `queue_full` y el número de tareas no cambia

#### Scenario: Subtarea no ocupa el hueco raíz
- **GIVEN** `t1` en `running`
- **WHEN** se envía una tarea con `parent_id = t1`
- **THEN** la subtarea pasa a `running` sin esperar a que termine `t1`

#### Scenario: Padre inexistente
- **WHEN** se envía una tarea con `parent_id = "nope"`
- **THEN** `submit` falla con `unknown_task` y no se crea la tarea

### Requirement: Máquina de estados de la tarea
Una tarea SHALL seguir `queued → running → (waiting_confirmation → running)* → {done, failed, cancelled, timeout}`. Toda transición SHALL ser atómica bajo un cerrojo por tarea, cualquier transición no listada SHALL rechazarse y un estado final SHALL ser definitivo.

#### Scenario: Transición válida
- **GIVEN** `t1` en `running`
- **WHEN** solicita confirmación
- **THEN** `t1` pasa a `waiting_confirmation` y, al aprobarse, vuelve a `running`

#### Scenario: Transición inválida
- **GIVEN** `t1` en `queued`
- **WHEN** se intenta pasar a `waiting_confirmation`
- **THEN** la transición se rechaza y `t1` sigue en `queued`

#### Scenario: Estado final definitivo
- **GIVEN** `t1` en `cancelled`
- **WHEN** el motor de ejecución entrega después un resultado `ok`
- **THEN** `t1` sigue en `cancelled` y el resultado tardío se ignora

#### Scenario: Correspondencia estado y resultado
- **GIVEN** una tarea que termina
- **WHEN** el `TaskResult` tiene `status` `ok` o `partial`
- **THEN** la tarea queda en `done`; con `error` queda en `failed`; con `cancelled` en `cancelled`; con `timeout` en `timeout`

### Requirement: Eventos de tarea
Además de los eventos del runner, el orquestador SHALL emitir `task.queued`, `task.running`, `task.progress {tool, step}` por cada `tool.call` (`step` creciente desde 1), `task.needs_confirmation {confirmation_id, tool, args}`, `task.confirmed {confirmation_id, approved}`, `task.cancelled {reason}` y `task.result {result}` como último evento. Todos SHALL escribirse también en el log JSONL de la tarea.

#### Scenario: Secuencia con confirmación rechazada
- **GIVEN** la tarea `t1` cuyo `worker` ejecuta `filesystem.list_directory` y después pide `filesystem.move_file` con `{"source": "/n/tmp.md", "destination": "/n/.trash/tmp.md"}`
- **WHEN** el usuario rechaza la confirmación `c1`
- **THEN** los eventos del orquestador, en orden, son `task.queued`, `task.running`, `task.progress {tool: "filesystem.list_directory", step: 1}`, `task.needs_confirmation {confirmation_id: "c1", tool: "filesystem.move_file", args: {...}}`, `task.confirmed {confirmation_id: "c1", approved: false}`, `task.cancelled {reason: "not_confirmed"}` y `task.result {result: {status: "cancelled", ...}}`

#### Scenario: Progreso por cada llamada
- **GIVEN** una tarea cuyo runner emite tres `tool.call`
- **WHEN** termina
- **THEN** se han emitido tres `task.progress` con `step` `1`, `2`, `3`

#### Scenario: Eventos en el log
- **GIVEN** una tarea terminada
- **WHEN** se lee su fichero JSONL
- **THEN** contiene los eventos del runner y los del orquestador con `seq` creciente y `task.result` es la última línea

### Requirement: Flujo de eventos por tarea
`events(task_id)` SHALL devolver un iterador asíncrono que entrega primero los eventos ya emitidos y después los nuevos, en orden, y SHALL terminar tras `task.result`. Un `task_id` desconocido SHALL fallar con `unknown_task`.

#### Scenario: Suscripción tardía
- **GIVEN** `t1` ya emitió `task.queued` y `task.running`
- **WHEN** un consumidor llama a `events("t1")`
- **THEN** recibe esos dos eventos y después los siguientes hasta `task.result`, y el iterador termina

#### Scenario: Varios consumidores
- **GIVEN** dos consumidores de `events("t1")`
- **WHEN** `t1` emite `task.progress`
- **THEN** ambos reciben el mismo evento

### Requirement: Cancelación externa
`cancel(task_id, reason="user")` SHALL atenderse aunque el runner esté bloqueado: SHALL marcar la tarea como cancelada, interrumpir la ejecución, impedir que se ejecute ninguna tool posterior, emitir `task.cancelled {reason}` y terminar con `task.result` de `status = "cancelled"`. Cancelar una tarea en `queued` SHALL retirarla de la cola; cancelar una tarea en estado final SHALL ser un no-op.

#### Scenario: Cancelación durante espera de confirmación
- **GIVEN** `t1` en `waiting_confirmation`
- **WHEN** llega `cancel("t1")`
- **THEN** la confirmación pendiente queda inválida, la tool no se ejecuta, se emite `task.cancelled {reason: "user"}` y el resultado tiene `status = "cancelled"`

#### Scenario: Cancelación durante una tool larga
- **GIVEN** `t1` en `running` con una tool en ejecución que tarda 2 s
- **WHEN** llega `cancel("t1")` y después el runner intenta otra tool
- **THEN** `cancel` devuelve sin esperar a la tool, la siguiente tool no se ejecuta y el resultado es `cancelled`

#### Scenario: Cancelación en cola
- **GIVEN** `t2` en `queued`
- **WHEN** llega `cancel("t2")`
- **THEN** `t2` pasa a `cancelled` sin haber ejecutado el runner y la cola ya no la contiene

#### Scenario: Cancelación de tarea terminada
- **GIVEN** `t1` en `done`
- **WHEN** llega `cancel("t1")`
- **THEN** no cambia el estado ni se emite ningún evento

### Requirement: Timeout de tarea
Una tarea SHALL disponer de `limits.task_timeout_s` (300 s) desde que entra en `running`, incluyendo las esperas de confirmación y la conexión del motor. Al expirar SHALL interrumpirse la ejecución y la tarea SHALL terminar en `timeout` con `task.result` de `status = "timeout"`.

#### Scenario: Timeout con confirmación pendiente
- **GIVEN** `task_timeout_s = 1` y `t1` en `waiting_confirmation` sin respuesta
- **WHEN** transcurre 1 s desde `task.running`
- **THEN** `t1` pasa a `timeout`, la confirmación pendiente queda inválida y el resultado tiene `status = "timeout"`

#### Scenario: Timeout de runner que no termina
- **GIVEN** `task_timeout_s = 1` y un runner que nunca devuelve
- **WHEN** transcurre 1 s
- **THEN** se interrumpe el runner y `task.result.status` es `timeout`

### Requirement: Espera del resultado
`wait(task_id)` SHALL devolver el `TaskResult` cuando la tarea alcance un estado final, SHALL devolverlo de inmediato si ya terminó, y SHALL fallar con `unknown_task` para un identificador desconocido. Un fallo inesperado del runner SHALL producir `failed` con un `TaskResult` de `status = "error"` y el mensaje en `errores`.

#### Scenario: Resultado disponible
- **GIVEN** `t1` terminada con `status = "ok"`
- **WHEN** se llama a `wait("t1")`
- **THEN** devuelve ese `TaskResult` sin bloquear

#### Scenario: Runner que lanza excepción
- **GIVEN** un runner que lanza `boom`
- **WHEN** `wait("t1")` resuelve
- **THEN** `t1` está en `failed` y el resultado es `{status: "error", errores: ["boom"], ...}`
