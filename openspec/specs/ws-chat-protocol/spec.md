# ws-chat-protocol Specification

## Purpose
Define el protocolo WebSocket versionado de `/ws/chat` entre el navegador y el servidor local: sobre de mensaje, tipos cliente/servidor, numeración `seq` por conversación, reconexión con reenvío de estado, exclusividad del socket, uso de tokens con alerta y tipos reservados para audio.

## Requirements

### Requirement: Sobre de mensaje versionado
Todo mensaje en `/ws/chat` SHALL ser un objeto JSON `{v: 1, type, seq, conversation_id, message_id?, task_id?, payload}`. En los mensajes del servidor `seq` SHALL ser un entero positivo; en los del cliente `seq` SHALL ser un entero propio del cliente que el servidor ignora. Un mensaje con `v` distinto de `1`, sin `type` o con JSON inválido SHALL responder `error {code: "bad_envelope", detail}` y, si `v` no es `1`, cerrar la conexión con código `1002`.

#### Scenario: Versión no soportada
- **WHEN** el cliente envía `{"v": 2, "type": "hello", "seq": 1, "conversation_id": null, "payload": {}}`
- **THEN** recibe `error {code: "bad_envelope"}` y la conexión se cierra con `1002`

#### Scenario: JSON inválido
- **WHEN** el cliente envía `{not json`
- **THEN** recibe `error {code: "bad_envelope"}` y la conexión sigue abierta

### Requirement: Tipos de mensaje del cliente
El servidor SHALL aceptar exactamente los tipos `hello`, `user.text`, `confirm`, `cancel` y `set_mode`; los tipos reservados `audio.start`, `audio.chunk` y `audio.end` SHALL responder `error {code: "not_implemented"}`; cualquier otro tipo SHALL responder `error {code: "unknown_type"}`. Cualquier mensaje distinto de `hello` antes de un `hello` aceptado SHALL responder `error {code: "hello_required"}`.

#### Scenario: Tipo reservado de audio
- **GIVEN** un `hello` aceptado
- **WHEN** el cliente envía `audio.start`
- **THEN** recibe `error {code: "not_implemented"}` y la conexión sigue abierta

#### Scenario: Mensaje antes del hello
- **WHEN** el cliente envía `user.text` como primer mensaje
- **THEN** recibe `error {code: "hello_required"}` y no se crea ningún mensaje

#### Scenario: Tipo desconocido
- **WHEN** el cliente envía `type: "ping"`
- **THEN** recibe `error {code: "unknown_type"}`

### Requirement: Validación estricta del payload
El servidor SHALL validar el `payload` de cada tipo antes de procesarlo y responder `error {code: "bad_payload", detail}` sin cerrar la conexión cuando no cumpla su forma. Booleanos y enteros SHALL ser estrictos (`"false"`, `1` o `1.5` no se convierten); los campos desconocidos se ignoran.

#### Scenario: Formas aceptadas por tipo
- **WHEN** llega `hello {conversation_id: string|null, last_seq?: entero ≥ 0}`, `user.text {text: string, client_id?: string}`, `confirm {confirmation_id: string, approved: boolean, task_id?: string}`, `cancel {task_id: string}` o `set_mode {reply_mode: string}`
- **THEN** el payload se acepta y se procesa

#### Scenario: Aprobación como cadena
- **GIVEN** una confirmación pendiente `a3f`
- **WHEN** el cliente envía `confirm {confirmation_id: "a3f", approved: "false"}`
- **THEN** recibe `error {code: "bad_payload"}` y la confirmación sigue pendiente

#### Scenario: last_seq inválido
- **WHEN** el cliente envía `hello {conversation_id: null, last_seq: "abc"}` o `last_seq: -1`
- **THEN** recibe `error {code: "bad_payload"}` y la conexión sigue abierta

### Requirement: Apertura con `hello`
`hello {conversation_id | null, last_seq?}` SHALL abrir la conversación indicada o crear una nueva en el canal `web` si es `null`, y responder `hello.ok {conversation_id, stream_id, reply_mode, last_seq, state}`. Un `conversation_id` inexistente SHALL responder `error {code: "unknown_conversation"}`. El `hello.ok` SHALL enviarse con la cola del socket ya conectada y su `state` SHALL pasar por la misma redacción de secretos que el resto de sobres.

#### Scenario: Contenido de hello.ok
- **WHEN** el servidor responde `hello.ok`
- **THEN** `stream_id` identifica la instancia del flujo de `seq` (estable entre reconexiones, distinto tras un reinicio o cambio de conversación), `reply_mode` es el modo persistido o el de configuración y `state` describe el turno en curso, las tareas activas y la confirmación pendiente

#### Scenario: Evento publicado durante el envío de hello.ok
- **GIVEN** un cliente conectando
- **WHEN** se publica un `assistant.final` mientras se envía `hello.ok`
- **THEN** el cliente lo recibe después de `hello.ok` sin pérdida

#### Scenario: Conversación nueva
- **WHEN** el cliente envía `hello {conversation_id: null}`
- **THEN** recibe `hello.ok` con un `conversation_id` nuevo, `stream_id`, `reply_mode`, `last_seq: 0` y `state: {turn_in_progress: false, active_tasks: [], pending_confirmation: null}`

#### Scenario: stream_id tras un reinicio
- **GIVEN** un cliente con `stream_id: "s-1"` y `last_seq: 40`
- **WHEN** el servidor se reinicia y el cliente reconecta
- **THEN** recibe `hello.ok` con un `stream_id` distinto; el cliente vuelve a pedir el historial y reinicia su cursor con el `last_seq` recibido

#### Scenario: Conversación existente
- **GIVEN** la conversación `c-1` con mensajes previos
- **WHEN** el cliente envía `hello {conversation_id: "c-1"}`
- **THEN** recibe `hello.ok {conversation_id: "c-1"}` y los mensajes previos se obtienen por `GET /api/conversations/c-1/messages`

#### Scenario: Conversación desconocida
- **WHEN** el cliente envía `hello {conversation_id: "nope"}`
- **THEN** recibe `error {code: "unknown_conversation"}` y puede enviar otro `hello`

### Requirement: Un solo socket activo por conversación
Mientras una conversación tenga un socket aceptado, un segundo `hello` para la misma conversación desde otro socket SHALL responder `error {code: "conversation_busy", detail}` y cerrar ese segundo socket con código `1008`; al cerrarse el primero, la conversación SHALL quedar libre para un nuevo `hello`. La transición completa de apertura, cambio y adjunción SHALL ser atómica frente a otros `hello` concurrentes: de dos `hello` simultáneos exactamente uno recibe `hello.ok`.

#### Scenario: Dos hello simultáneos
- **WHEN** los sockets A y B envían `hello` a la vez mientras el `hello.ok` de A aún se está enviando
- **THEN** solo A recibe `hello.ok`, B recibe `error {code: "conversation_busy"}` y solo A recibe los eventos siguientes

### Requirement: Nueva conversación desde el socket propietario
El socket propietario SHALL poder enviar `hello {conversation_id: null | otra}` mientras no haya turno ni tareas activas: el servidor cierra la sesión actual, abre la nueva y responde `hello.ok` con el nuevo `conversation_id`, `stream_id` y `last_seq: 0`. Con un turno o tareas en curso SHALL responder `error {code: "conversation_busy"}` sin alterar la conversación ni el socket.

#### Scenario: Reinicio del estado del cliente
- **GIVEN** un cliente con mensajes, tareas y una confirmación en pantalla
- **WHEN** recibe `hello.ok` con un `conversation_id` distinto del actual
- **THEN** reinicia su cursor y su estado (mensajes, tareas, confirmación)

#### Scenario: Nueva conversación en reposo
- **GIVEN** el socket A con un turno terminado en `c-1`
- **WHEN** A envía `hello {conversation_id: null}`
- **THEN** recibe `hello.ok {conversation_id: "c-2", last_seq: 0}` con un `stream_id` nuevo y los eventos siguientes llegan con `seq` desde 1

#### Scenario: Nueva conversación con turno en curso
- **GIVEN** el socket A con un turno en curso en `c-1`
- **WHEN** A envía `hello {conversation_id: null}`
- **THEN** recibe `error {code: "conversation_busy"}` y sigue recibiendo los eventos de `c-1`

#### Scenario: Segundo socket rechazado
- **GIVEN** el socket A con `hello {conversation_id: "c-1"}` aceptado
- **WHEN** el socket B envía `hello {conversation_id: "c-1"}`
- **THEN** B recibe `error {code: "conversation_busy"}` y se cierra con `1008`; A sigue recibiendo eventos

#### Scenario: Relevo tras el cierre
- **GIVEN** el socket A cerrado
- **WHEN** el socket B envía `hello {conversation_id: "c-1"}`
- **THEN** B recibe `hello.ok`

### Requirement: Mensaje de usuario y aceptación
`user.text {text, client_id?}` SHALL crear el mensaje de usuario (respetando los prefijos `/v`, `/t`, `/b`), responder `user.accepted {message_id, effective_mode, client_id}` antes de iniciar el turno y terminar el turno con `assistant.final {display_text, speech_text, message_id}`. Un `text` vacío o un turno ya en curso SHALL responder `error` (`empty_text` / `turn_in_progress`) sin encolar nada.

#### Scenario: Bloqueo de envíos en el cliente
- GIVEN el cliente envía `user.text` con `client_id`
- WHEN aún no ha recibido el `user.accepted` con ese `client_id` ni un `error`
- THEN no permite otro envío y conserva el borrador si la transmisión falló.

#### Scenario: Acuse correlacionado
- **WHEN** el cliente envía `user.text {text: "hola", client_id: "r-1"}`
- **THEN** recibe `user.accepted {client_id: "r-1"}` y solo entonces vuelve a aceptar un envío

#### Scenario: Turno completo
- **GIVEN** un `hello` aceptado con `reply_mode: "text"`
- **WHEN** el cliente envía `user.text {text: "hola"}`
- **THEN** recibe, en orden, `user.accepted {message_id, effective_mode: "text"}` y `assistant.final {display_text, speech_text: null, message_id}` con `seq` crecientes

#### Scenario: Prefijo de modo
- **GIVEN** `reply_mode: "text"`
- **WHEN** el cliente envía `user.text {text: "/v qué hora es"}`
- **THEN** `user.accepted.effective_mode` es `voice` y `assistant.final.speech_text` no es nulo

#### Scenario: Turno en curso
- **GIVEN** un turno iniciado y sin `assistant.final`
- **WHEN** el cliente envía otro `user.text`
- **THEN** recibe `error {code: "turn_in_progress"}` y el segundo texto no se envía al `front`

#### Scenario: Texto vacío
- **WHEN** el cliente envía `user.text {text: "   "}`
- **THEN** recibe `error {code: "empty_text"}`

### Requirement: Streaming y frase de espera
Durante un turno el servidor MAY enviar cero o más `assistant.delta {text}` (fragmentos de `display_text` del mismo `message_id`) y `assistant.wait {text}` cuando una delegación supera 3 s; `assistant.final.display_text` SHALL ser siempre el texto completo y autoritativo. Cuando el motor del `front` no entrega fragmentos (respuesta estructurada sin parciales), el servidor SHALL enviar solo `assistant.final`.

#### Scenario: Motor con fragmentos
- **GIVEN** un motor del `front` que entrega los fragmentos `"Hola"` y `", Renzo"`
- **WHEN** se procesa el turno
- **THEN** el cliente recibe `assistant.delta {text: "Hola"}`, `assistant.delta {text: ", Renzo"}` y `assistant.final {display_text: "Hola, Renzo"}` con el mismo `message_id`

#### Scenario: Motor sin fragmentos
- **GIVEN** un motor del `front` que solo devuelve la respuesta completa
- **WHEN** se procesa el turno
- **THEN** el cliente recibe `assistant.final` sin ningún `assistant.delta`

#### Scenario: Frase de espera
- **GIVEN** una delegación que tarda más de 3 s
- **WHEN** transcurren 3 s desde que empezó
- **THEN** el cliente recibe `assistant.wait {text: "<frase de espera del front>"}`

### Requirement: Eventos de tarea y de tools
Por cada tarea delegada el servidor SHALL reenviar `task.queued`, `task.running`, `task.progress`, `task.needs_confirmation` (con `expires_in_s`), `task.confirmed`, `task.cancelled` y `task.result` con el mismo `payload` que el orquestador y `task_id` en el sobre; `tool.call {tool, args}` y `tool.result {tool, ok, duration_ms, error}` con los secretos redactados; y, en subtareas, el `parent_id` en el `payload` junto con `subtask.started/finished` del padre.

#### Scenario: Confirmación pendiente
- **GIVEN** la tarea `t-9` de la conversación `c-1` que pide confirmar `filesystem.move_file`
- **WHEN** el orquestador emite `task.needs_confirmation`
- **THEN** el cliente recibe `{"v":1,"type":"task.needs_confirmation","seq":17,"conversation_id":"c-1","task_id":"t-9","payload":{"confirmation_id":"a3f…","tool":"filesystem.move_file","args":{"source":"/home/renzo/notas/tmp.md","destination":"/home/renzo/notas/.trash/tmp.md"},"expires_in_s":60}}`

#### Scenario: Subtarea con parent_id
- **GIVEN** la tarea `t-9` lanza la subtarea `s-1` con el agente `investigador`
- **WHEN** la subtarea emite `tool.call`
- **THEN** el cliente recibe `subtask.started {task_id: "s-1", agent: "investigador"}` con `task_id: "t-9"` y `tool.call` con `task_id: "s-1"` y `parent_id: "t-9"` en el `payload`

#### Scenario: Secretos redactados
- **GIVEN** un `tool.call` cuyos `args` contienen un valor de `config/.env`
- **WHEN** se reenvía
- **THEN** el valor aparece como `***`

#### Scenario: Ruta del log
- **WHEN** se reenvía `task.queued` de la tarea `t-9`
- **THEN** su `payload` incluye `log_path` con la ruta del fichero `logs/<fecha>/t-9.jsonl`

### Requirement: Confirmación y cancelación por WebSocket
`confirm {confirmation_id, approved}` SHALL resolver la misma confirmación pendiente que `POST /api/tasks/{task_id}/confirm` y `cancel {task_id}` la misma cancelación que `POST /api/tasks/{task_id}/cancel`; una confirmación inválida SHALL responder `error {code: "invalid_confirmation"}` y una tarea desconocida `error {code: "unknown_task"}`. Un "sí" dentro del contenido devuelto por una tool nunca SHALL contar como aprobación.

#### Scenario: Confirmación por WebSocket
- **GIVEN** `task.needs_confirmation` con `confirmation_id: "a3f"` recibido
- **WHEN** el cliente envía `confirm {confirmation_id: "a3f", approved: true}`
- **THEN** recibe `task.confirmed {confirmation_id: "a3f", approved: true}` y la tool se ejecuta

#### Scenario: Confirmación caducada
- **GIVEN** `task.needs_confirmation` recibido hace 61 s sin respuesta
- **WHEN** el cliente envía `confirm {confirmation_id: "a3f", approved: true}`
- **THEN** recibe `error {code: "invalid_confirmation"}` y la tarea ya terminó `cancelled` con `task.cancelled {reason: "not_confirmed"}`

#### Scenario: Cancelación por WebSocket
- **GIVEN** la tarea `t-9` en `running`
- **WHEN** el cliente envía `cancel {task_id: "t-9"}`
- **THEN** recibe `task.cancelled {reason: "user"}` y después `task.result` con `status: "cancelled"`

### Requirement: Cambio de modo por WebSocket
`set_mode {reply_mode}` SHALL persistir el modo igual que `PATCH /api/settings` y no SHALL producir respuesta propia salvo `error {code: "invalid_reply_mode"}` si el valor no es `auto|voice|text|both`; el modo persistido SHALL reflejarse en el siguiente `user.accepted.effective_mode` y en el `hello.ok` de una reconexión.

#### Scenario: Modo válido por WebSocket
- **WHEN** el cliente envía `set_mode {reply_mode: "text"}` y después `user.text {text: "hola"}`
- **THEN** `memory/settings.json` contiene `{"reply_mode": "text"}` y `user.accepted.effective_mode` es `text`

#### Scenario: Modo inválido
- **WHEN** el cliente envía `set_mode {reply_mode: "loud"}`
- **THEN** recibe `error {code: "invalid_reply_mode"}` y el fichero no cambia

### Requirement: Uso de tokens por tarea
Al terminar cada tarea o subtarea el servidor SHALL enviar `usage {task_id, input_tokens, output_tokens, cost_usd, cumulative_tokens, alert}` donde `cumulative_tokens` suma entrada y salida de la tarea raíz y de todas sus subtareas y `alert` es `true` cuando esa suma supera `limits.token_alert` (50 000). Al terminar un turno del `front` SHALL enviar `usage` con `task_id: null` y el consumo del turno.

#### Scenario: Alerta de tokens
- **GIVEN** `limits.token_alert = 50000` y la tarea `t-9` de `c-1` que termina con 41 200 tokens de entrada y 9 900 de salida
- **WHEN** se emite su `task.finished`
- **THEN** el cliente recibe `{"v":1,"type":"usage","seq":40,"conversation_id":"c-1","task_id":"t-9","payload":{"input_tokens":41200,"output_tokens":9900,"cost_usd":0.31,"cumulative_tokens":51100,"alert":true}}`

#### Scenario: Acumulado con subtareas
- **GIVEN** la tarea `t-9` con 30 000 tokens y su subtarea `s-1` con 25 000
- **WHEN** termina `s-1` y después `t-9`
- **THEN** el `usage` de `s-1` tiene `cumulative_tokens: 25000, alert: false` y el de `t-9` tiene `cumulative_tokens: 55000, alert: true`

#### Scenario: Consumo del turno del front
- **WHEN** termina un turno sin delegación con 1 200 tokens de entrada y 80 de salida
- **THEN** el cliente recibe `usage {task_id: null, input_tokens: 1200, output_tokens: 80, alert: false}` antes de `assistant.final`

### Requirement: `seq` monótono y reenvío en la reconexión
El servidor SHALL numerar cada mensaje con un `seq` creciente por conversación y conservar al menos los últimos 500; asignación, inserción en el búfer y encolado SHALL ser atómicos para que el socket reciba los `seq` en orden bajo backpressure. `hello {conversation_id, last_seq}` SHALL reenviar tras `hello.ok` solo los mensajes con `seq > last_seq`; si `last_seq` es anterior al primero conservado, `hello.ok` SHALL incluir `resync: true` sin reenviar nada.

#### Scenario: Invalidación del cursor en el cliente
- GIVEN un cliente con cursor `seq` y `stream_id` conocidos
- WHEN recibe `hello.ok` con `last_seq` menor que su cursor o con un `stream_id` distinto
- THEN reinicia el cursor, vuelve a cargar el historial y descarta todo mensaje con `seq` menor o igual al último visto.

#### Scenario: Estado activo solo desde el snapshot
- GIVEN `hello.ok.state` con la raíz activa y la confirmación pendiente
- WHEN llegan mensajes reenviados con `seq ≤ hello.ok.last_seq`
- THEN el estado activo y el plazo de la confirmación se reconstruyen solo desde `hello.ok.state`, sin que el reenvío los altere.

#### Scenario: Reconexión sin texto duplicado
- **GIVEN** una respuesta en streaming con `seq` 10..25 enviada y el cliente desconectado tras recibir hasta 18
- **WHEN** el cliente reconecta con `hello {conversation_id, last_seq: 18}`
- **THEN** recibe `hello.ok` con el estado actual y los mensajes con `seq` 19..25 solamente; el texto mostrado no se repite

#### Scenario: Estado reenviado con confirmación pendiente
- **GIVEN** la tarea `t-9` en `waiting_confirmation` desde hace 20 s y el cliente desconectado
- **WHEN** el cliente reconecta
- **THEN** `hello.ok.state` contiene `active_tasks: [{task_id: "t-9", parent_id: null, status: "waiting_confirmation"}]` y `pending_confirmation` con `confirmation_id`, `tool`, `args` y `expires_in_s` entre 39 y 40

#### Scenario: Historial demasiado antiguo
- **GIVEN** 700 mensajes enviados en la conversación
- **WHEN** el cliente reconecta con `last_seq: 10`
- **THEN** recibe `hello.ok {resync: true}` y ningún mensaje reenviado

### Requirement: Eventos de configuración y errores
El servidor SHALL reenviar `config.reloaded {agent, servers}` y `config.reload_failed {agent, error}` cuando el núcleo los emita, y SHALL comunicar cualquier fallo del turno como `error {code: "turn_failed", detail}` seguido del `assistant.final` con el texto de error del `front`, sin cerrar la conexión.

#### Scenario: Recarga de configuración
- **WHEN** el núcleo emite `config.reloaded {agent: "viernes", servers: ["filesystem", "fetch"]}`
- **THEN** el cliente recibe `config.reloaded` con ese `payload`

#### Scenario: Turno fallido
- **GIVEN** un motor del `front` que devuelve un turno con `error`
- **WHEN** se procesa el turno
- **THEN** el cliente recibe `error {code: "turn_failed", detail}` y `assistant.final` con el texto de error en español, y la conexión sigue abierta
