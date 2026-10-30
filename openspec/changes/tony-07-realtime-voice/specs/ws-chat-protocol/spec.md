## MODIFIED Requirements

### Requirement: Tipos de mensaje del cliente
El servidor SHALL aceptar exactamente los tipos de texto `hello`, `user.text`, `confirm`, `cancel`, `set_mode`, `audio.start`, `audio.end` y `playback.stopped`, y los frames binarios como audio de la intervención abierta; cualquier otro tipo SHALL responder `error {code: "unknown_type"}`. Cualquier mensaje distinto de `hello` antes de un `hello` aceptado SHALL responder `error {code: "hello_required"}`; un frame binario antes del `hello` SHALL descartarse con ese mismo error.

#### Scenario: Apertura de audio aceptada
- **GIVEN** un `hello` aceptado y la voz disponible
- **WHEN** el cliente envía `audio.start {sample_rate: 16000, channels: 1, format: "f32"}`
- **THEN** no recibe `error` y los frames binarios siguientes se aceptan como audio

#### Scenario: Mensaje antes del hello
- **WHEN** el cliente envía `user.text` como primer mensaje
- **THEN** recibe `error {code: "hello_required"}` y no se crea ningún mensaje

#### Scenario: Frame binario antes del hello
- **WHEN** el cliente envía un frame binario como primer mensaje
- **THEN** recibe `error {code: "hello_required"}` y el frame se descarta

#### Scenario: Tipo desconocido
- **WHEN** el cliente envía `type: "ping"`
- **THEN** recibe `error {code: "unknown_type"}`

#### Scenario: Tipo reservado de audio
- **WHEN** el cliente envía un sobre de texto con `type: "audio.chunk"`
- **THEN** recibe `error {code: "unknown_type"}`: el audio solo viaja como frames binarios tras `audio.start`, y `audio.start`/`audio.end` ya no responden `not_implemented`

#### Scenario: Fin de reproducción aceptado
- **GIVEN** un `hello` aceptado
- **WHEN** el cliente envía `playback.stopped {message_id: "m-2"}`
- **THEN** no recibe ninguna respuesta ni `error`, también si `m-2` no tiene síntesis en curso

### Requirement: Validación estricta del payload
El servidor SHALL validar el `payload` de cada tipo antes de procesarlo y responder `error {code: "bad_payload", detail}` sin cerrar la conexión cuando no cumpla su forma. Booleanos y enteros SHALL ser estrictos (`"false"`, `1` o `1.5` no se convierten); los campos desconocidos se ignoran.

#### Scenario: Formas aceptadas por tipo
- **WHEN** llega `hello {conversation_id: string|null, last_seq?: entero ≥ 0}`, `user.text {text: string, client_id?: string}`, `confirm {confirmation_id: string, approved: boolean, task_id?: string}`, `cancel {task_id: string}`, `set_mode {reply_mode: string}` o `playback.stopped {message_id: string}`
- **THEN** el payload se acepta y se procesa

#### Scenario: Aprobación como cadena
- **GIVEN** una confirmación pendiente `a3f`
- **WHEN** el cliente envía `confirm {confirmation_id: "a3f", approved: "false"}`
- **THEN** recibe `error {code: "bad_payload"}` y la confirmación sigue pendiente

#### Scenario: last_seq inválido
- **WHEN** el cliente envía `hello {conversation_id: null, last_seq: "abc"}` o `last_seq: -1`
- **THEN** recibe `error {code: "bad_payload"}` y la conexión sigue abierta

#### Scenario: playback.stopped sin message_id
- **WHEN** el cliente envía `playback.stopped {}`
- **THEN** recibe `error {code: "bad_payload"}` y la conexión sigue abierta
