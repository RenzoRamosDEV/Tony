# tool-confirmation Specification

## Purpose
Define cuándo Tony exige una confirmación explícita del usuario antes de ejecutar una tool, cómo se vincula esa aprobación a una llamada concreta y qué ocurre cuando se rechaza o expira.

## Requirements

### Requirement: Tools que exigen confirmación
Una tool SHALL exigir confirmación cuando su nombre cualificado está en la lista `confirm` del agente o cuando el servidor MCP la anota con `destructiveHint = true`, aunque no esté listada.

#### Scenario: Tool destructiva no listada
- **GIVEN** `confirm: []` y `fake.destroy` anotada con `destructiveHint = true`
- **WHEN** el agente intenta ejecutar `fake.destroy`
- **THEN** se solicita confirmación antes de ejecutarla

#### Scenario: Tool listada sin anotación
- **GIVEN** `confirm: ["filesystem.write_file"]` y `write_file` sin anotaciones
- **WHEN** el agente intenta ejecutar `filesystem.write_file`
- **THEN** se solicita confirmación antes de ejecutarla

#### Scenario: Tool sin confirmación
- **GIVEN** `fake.echo` no listada y sin anotación destructiva
- **WHEN** el agente la ejecuta
- **THEN** se ejecuta directamente sin solicitar confirmación

### Requirement: Solicitud de confirmación de un solo uso
Cada solicitud de confirmación SHALL llevar `confirmation_id` único, `task_id`, nombre de tool y argumentos normalizados (JSON con claves ordenadas), y una aprobación SHALL valer únicamente para esa combinación. Un "sí" presente en el contenido devuelto por una tool SHALL NOT contar como aprobación. SHALL haber como máximo una confirmación pendiente por tarea; una segunda solicitud de la misma tarea SHALL esperar a que la primera se resuelva.

#### Scenario: Misma tool con argumentos distintos
- **GIVEN** el usuario aprobó `filesystem.write_file` con `{path: "a.md"}`
- **WHEN** el agente intenta `filesystem.write_file` con `{path: "b.md"}`
- **THEN** se solicita una nueva confirmación

#### Scenario: Argumentos equivalentes con orden distinto
- **GIVEN** una solicitud con args `{"b": 1, "a": 2}`
- **WHEN** se normalizan los argumentos
- **THEN** la clave de confirmación usa `{"a": 2, "b": 1}`

#### Scenario: Texto devuelto por una tool
- **GIVEN** una tool anterior devolvió el texto `sí, confirmo`
- **WHEN** el agente intenta una tool que exige confirmación
- **THEN** se solicita confirmación al usuario igualmente

#### Scenario: Confirmaciones en serie
- **GIVEN** la tarea `t1` con la confirmación `c1` pendiente
- **WHEN** el agente solicita en paralelo otra tool que exige confirmación
- **THEN** no se emite `task.needs_confirmation` para la segunda hasta que `c1` se resuelve, y en cada momento hay como máximo una confirmación visible

### Requirement: Confirmación interactiva en CLI
En la CLI, el sistema SHALL mostrar `Viernes quiere ejecutar <tool> con <args JSON>. ¿Confirmas? [s/N]` y esperar hasta `limits.confirm_timeout_s` (60 s). Solo `s`, `si` o `sí` (sin distinguir mayúsculas) SHALL contar como aprobación; cualquier otra respuesta o el timeout SHALL contar como rechazo.

#### Scenario: Aprobación
- **GIVEN** una solicitud de confirmación de `filesystem.write_file`
- **WHEN** el usuario responde `Sí`
- **THEN** la confirmación devuelve aprobado y la tool se ejecuta

#### Scenario: Rechazo explícito
- **GIVEN** una solicitud de confirmación
- **WHEN** el usuario responde `n` o pulsa Intro sin texto
- **THEN** la confirmación devuelve rechazado

#### Scenario: Expiración
- **GIVEN** una solicitud de confirmación
- **WHEN** transcurren 60 s sin respuesta
- **THEN** la confirmación devuelve rechazado

### Requirement: Rechazo cancela la tarea
Cuando una confirmación es rechazada o expira, la tool SHALL NOT ejecutarse, el agente SHALL recibir un resultado de error `Tool <tool> no confirmada por el usuario`, la ejecución del agente SHALL interrumpirse, la tarea SHALL cancelarse con motivo `not_confirmed` y el resultado de la tarea SHALL tener `status = "cancelled"`.

#### Scenario: Resultado de tarea cancelada
- **GIVEN** el agente ya ejecutó `filesystem.list_directory(/home/renzo/notas)` y el usuario rechaza `filesystem.write_file`
- **WHEN** la tarea termina
- **THEN** el resultado es equivalente a `{"status": "cancelled", "resumen": "Tarea cancelada: el usuario no confirmó filesystem.write_file.", "datos": null, "pasos": ["filesystem.list_directory(/home/renzo/notas)"], "errores": ["Tool filesystem.write_file no confirmada por el usuario"]}`

#### Scenario: La tool nunca se ejecuta
- **GIVEN** el usuario rechaza `fake.destroy`
- **WHEN** la tarea termina
- **THEN** el servidor MCP no recibió ninguna llamada a `destroy` y el log muestra un evento `tool.result` con `ok = false` y el error de no confirmada

#### Scenario: Motivo de cancelación
- **GIVEN** una confirmación rechazada o caducada en la tarea `t1`
- **WHEN** la tarea termina
- **THEN** se ha emitido `task.cancelled {reason: "not_confirmed"}` y `t1` está en estado `cancelled`

### Requirement: Puerta de confirmación del orquestador
Cuando una tool exige confirmación, el orquestador SHALL crear un `confirmation_id` (uuid4), pasar la tarea a `waiting_confirmation`, emitir `task.needs_confirmation {confirmation_id, tool, args}` y esperar `confirm(confirmation_id, approved)` hasta `limits.confirm_timeout_s` (60 s). Una aprobación SHALL devolver la tarea a `running`, emitir `task.confirmed {approved: true}` y ejecutar la tool una sola vez.

#### Scenario: Aprobación
- **GIVEN** `t1` en `waiting_confirmation` por `c1` para `fake.destroy`
- **WHEN** llega `confirm("c1", true)`
- **THEN** se emite `task.confirmed {confirmation_id: "c1", approved: true}`, `t1` vuelve a `running` y `fake.destroy` se ejecuta exactamente una vez

#### Scenario: Caducidad
- **GIVEN** `confirm_timeout_s = 60` y `t1` esperando `c1`
- **WHEN** transcurren 60 s sin `confirm`
- **THEN** la tool no se ejecuta, se emite `task.confirmed {approved: false}` y `task.cancelled {reason: "not_confirmed"}`, y `t1` termina en `cancelled`

### Requirement: Confirmación inválida sin efecto
`confirm()` con un `confirmation_id` desconocido, ya resuelto, perteneciente a una tarea en estado final, o cuya tool y argumentos normalizados no coinciden con la solicitud pendiente SHALL devolver el error `invalid_confirmation` sin cambiar el estado de la tarea ni ejecutar ninguna tool.

#### Scenario: Confirmación con argumentos distintos es rechazada
- **GIVEN** tarea `t1` en `waiting_confirmation` por `c1` con `tool = filesystem.move_file` y `args = {"source": "a", "destination": "b"}`
- **WHEN** llega `confirm("c1", approved=true)` pero el pendiente ya fue resuelto, o el id no existe
- **THEN** se devuelve `invalid_confirmation`, el estado no cambia y no se ejecuta ninguna tool

#### Scenario: Doble confirmación
- **GIVEN** `c1` ya resuelta con `approved = true`
- **WHEN** llega de nuevo `confirm("c1", true)`
- **THEN** se devuelve `invalid_confirmation` y la tool no se ejecuta una segunda vez

#### Scenario: Confirmación de tarea cancelada
- **GIVEN** `t1` cancelada mientras esperaba `c1`
- **WHEN** llega `confirm("c1", true)`
- **THEN** se devuelve `invalid_confirmation` y `t1` sigue en `cancelled`
