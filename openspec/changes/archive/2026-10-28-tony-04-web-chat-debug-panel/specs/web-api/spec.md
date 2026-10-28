# Spec Delta

## Purpose

Define los endpoints HTTP JSON del servidor web local: salud, ajustes de respuesta, confirmación y cancelación de tareas, historial de conversaciones y memoria del usuario, con un formato de error uniforme.

## ADDED Requirements

### Requirement: Formato de error uniforme
Toda respuesta de error de la API (`4xx`/`5xx`) SHALL ser JSON con la forma `{error: <código en snake_case>, detail: <texto>}`; los errores de validación del cuerpo SHALL usar `422` con `error: "validation_error"` y una ruta no existente bajo `/api/` SHALL responder `404` con `error: "not_found"`.

#### Scenario: Ruta desconocida
- **WHEN** llega `GET /api/nada`
- **THEN** la respuesta es `404` con `{error: "not_found", detail}`

#### Scenario: Cuerpo inválido
- **WHEN** llega `PATCH /api/settings` con cuerpo `{"reply_mode": 3}`
- **THEN** la respuesta es `422` con `{error: "validation_error", detail}`

### Requirement: `GET /api/health`
`GET /api/health` SHALL responder `200` con `{status: "ok", version, front, worker, mcp: [{name, state, tool_count}]}`, donde `front` y `worker` son los nombres de los agentes resueltos por rol y `mcp` describe los servidores MCP del `worker` de la generación en uso (lista vacía si aún no se ha arrancado ninguna).

#### Scenario: Salud antes de la primera tarea
- **GIVEN** `front: jarvis`, `worker: viernes` y ninguna tarea ejecutada
- **WHEN** llega `GET /api/health`
- **THEN** la respuesta es `{status: "ok", version: "<versión del paquete>", front: "jarvis", worker: "viernes", mcp: []}`

#### Scenario: Salud con servidores arrancados
- **GIVEN** el `worker` con el servidor `filesystem` conectado con 11 tools
- **WHEN** llega `GET /api/health`
- **THEN** `mcp` contiene `{name: "filesystem", state: "ready", tool_count: 11}`

### Requirement: `GET /api/settings`
`GET /api/settings` SHALL responder `200` con `{reply_mode, reply_mode_source}` donde `reply_mode` es el modo persistido en `memory/settings.json` si existe o el de la configuración global en caso contrario, y `reply_mode_source` es `settings` o `yaml` respectivamente.

#### Scenario: Sin ajustes persistidos
- **GIVEN** no existe `memory/settings.json` y `reply_mode: auto` en la configuración global
- **WHEN** llega `GET /api/settings`
- **THEN** la respuesta es `{reply_mode: "auto", reply_mode_source: "yaml"}`

#### Scenario: Con ajustes persistidos
- **GIVEN** `memory/settings.json` contiene `{"reply_mode": "text"}`
- **WHEN** llega `GET /api/settings`
- **THEN** la respuesta es `{reply_mode: "text", reply_mode_source: "settings"}`

### Requirement: `PATCH /api/settings`
`PATCH /api/settings` con cuerpo `{reply_mode}` SHALL validar el valor contra `auto|voice|text|both`, persistirlo en `memory/settings.json` con escritura atómica y responder `200` con `{reply_mode, reply_mode_source: "settings"}`; un valor inválido SHALL responder `422` sin modificar el fichero.

#### Scenario: Modo válido
- **WHEN** llega `PATCH /api/settings` con `{"reply_mode": "voice"}`
- **THEN** la respuesta es `200` `{reply_mode: "voice", reply_mode_source: "settings"}` y `memory/settings.json` contiene `{"reply_mode": "voice"}`

#### Scenario: Modo inválido
- **GIVEN** `memory/settings.json` contiene `{"reply_mode": "text"}`
- **WHEN** llega `PATCH /api/settings` con `{"reply_mode": "loud"}`
- **THEN** la respuesta es `422` `{error: "validation_error", detail}` y el fichero sigue siendo `{"reply_mode": "text"}`

#### Scenario: Efecto en el siguiente mensaje
- **GIVEN** `PATCH /api/settings` con `{"reply_mode": "both"}` aceptado
- **WHEN** el cliente envía el siguiente `user.text` sin prefijo
- **THEN** `user.accepted.effective_mode` es `both`

### Requirement: `POST /api/tasks/{task_id}/confirm`
`POST /api/tasks/{task_id}/confirm` con cuerpo `{confirmation_id, approved}` SHALL resolver la confirmación pendiente identificada por `confirmation_id` (de una tarea del orquestador o de una tool del `front`) y responder `200` `{ok: true}`; si no existe, ya se resolvió, caducó o no pertenece a `task_id`, SHALL responder `409` `{error: "invalid_confirmation", detail}` sin ningún efecto.

#### Scenario: Confirmación aprobada por HTTP
- **GIVEN** la tarea `t-9` en `waiting_confirmation` con `confirmation_id: "a3f"` para `filesystem.move_file`
- **WHEN** llega `POST /api/tasks/t-9/confirm` con `{"confirmation_id": "a3f", "approved": true}`
- **THEN** la respuesta es `200` `{ok: true}`, la tool se ejecuta y el socket recibe `task.confirmed {confirmation_id: "a3f", approved: true}`

#### Scenario: Confirmación rechazada por HTTP
- **GIVEN** la misma confirmación pendiente
- **WHEN** llega `{"confirmation_id": "a3f", "approved": false}`
- **THEN** la respuesta es `200`, la tool no se ejecuta y la tarea termina `cancelled`

#### Scenario: Confirmación inválida
- **WHEN** llega `POST /api/tasks/t-9/confirm` con `{"confirmation_id": "nope", "approved": true}`
- **THEN** la respuesta es `409` `{error: "invalid_confirmation", detail}` y la tarea no cambia de estado

#### Scenario: Confirmación de otra tarea
- **GIVEN** `confirmation_id: "a3f"` pendiente de la tarea `t-9`
- **WHEN** llega `POST /api/tasks/t-1/confirm` con `{"confirmation_id": "a3f", "approved": true}`
- **THEN** la respuesta es `409` y `a3f` sigue pendiente

#### Scenario: Segunda respuesta
- **GIVEN** `a3f` ya resuelta por WebSocket
- **WHEN** llega `POST /api/tasks/t-9/confirm` con `{"confirmation_id": "a3f", "approved": false}`
- **THEN** la respuesta es `409` y la decisión anterior se mantiene

### Requirement: `POST /api/tasks/{task_id}/cancel`
`POST /api/tasks/{task_id}/cancel` SHALL cancelar la tarea con motivo `user` (y, si pertenece al turno en curso, interrumpir al `front` como hace `/cancel` en la terminal) y responder `200` `{ok: true}`; una tarea desconocida SHALL responder `404` `{error: "unknown_task", detail}` y una tarea ya terminada SHALL responder `200` sin efecto.

#### Scenario: Cancelación de tarea activa
- **GIVEN** la tarea `t-9` en `running`
- **WHEN** llega `POST /api/tasks/t-9/cancel`
- **THEN** la respuesta es `200`, el socket recibe `task.cancelled {reason: "user"}` y `task.result` con `status: "cancelled"`

#### Scenario: Tarea desconocida
- **WHEN** llega `POST /api/tasks/nope/cancel`
- **THEN** la respuesta es `404` `{error: "unknown_task", detail}`

### Requirement: `GET /api/conversations`
`GET /api/conversations` SHALL responder `200` con las 20 conversaciones más recientes de cualquier canal, de la más nueva a la más antigua, cada una como `{id, channel, created_at}`.

#### Scenario: Listado reciente
- **GIVEN** 25 conversaciones creadas en orden, 3 de ellas del canal `cli`
- **WHEN** llega `GET /api/conversations`
- **THEN** la respuesta contiene 20 elementos, el primero es la última creada y cada uno tiene `id`, `channel` y `created_at`

### Requirement: `GET /api/conversations/{id}/messages`
`GET /api/conversations/{id}/messages` SHALL responder `200` con todos los mensajes de la conversación en orden cronológico ascendente, cada uno como `{id, role, content, reply_mode, created_at}` con los secretos ya redactados; un `id` desconocido SHALL responder `404` `{error: "unknown_conversation", detail}`.

#### Scenario: Mensajes de una conversación
- **GIVEN** la conversación `c1` con un mensaje de usuario y una respuesta
- **WHEN** llega `GET /api/conversations/c1/messages`
- **THEN** la respuesta es una lista de dos elementos, el primero con `role: "user"` y el segundo con `role: "assistant"` y su `reply_mode`

#### Scenario: Conversación desconocida
- **WHEN** llega `GET /api/conversations/nope/messages`
- **THEN** la respuesta es `404` `{error: "unknown_conversation", detail}`

### Requirement: `GET /api/memory`
`GET /api/memory` SHALL responder `200` con `{content, lines}` donde `content` es el texto completo de `memory/preferences.md` (cadena vacía si no existe) y `lines` el número de preferencias.

#### Scenario: Memoria con preferencias
- **GIVEN** `memory/preferences.md` con dos líneas `- [2026-10-28] Prefiere respuestas breves` y `- [2026-10-28] Usa español`
- **WHEN** llega `GET /api/memory`
- **THEN** `content` contiene ambas líneas y `lines` es `2`

#### Scenario: Memoria vacía
- **GIVEN** no existe `memory/preferences.md`
- **WHEN** llega `GET /api/memory`
- **THEN** la respuesta es `{content: "", lines: 0}`
