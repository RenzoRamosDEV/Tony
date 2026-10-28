# Spec Delta

## MODIFIED Requirements

### Requirement: Tipos de mensaje del cliente
El servidor SHALL aceptar exactamente los tipos de texto `hello`, `user.text`, `confirm`, `cancel`, `set_mode`, `audio.start` y `audio.end`, y los frames binarios WebSocket como fragmentos de audio de la intervención abierta; cualquier otro tipo SHALL responder `error {code: "unknown_type"}`. Cualquier mensaje distinto de `hello` antes de un `hello` aceptado SHALL responder `error {code: "hello_required"}`; un frame binario antes del `hello` SHALL descartarse con `error {code: "hello_required"}`.

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

## ADDED Requirements

### Requirement: Tipos de mensaje de voz del servidor
Además de los tipos existentes, el servidor SHALL emitir `stt.final {text, message_id}`, `tts.start {message_id}`, `tts.chunk.meta {message_id, seq, sentence_index}` seguido de un frame binario, `tts.end {message_id}` y `tts.cancelled {message_id}`, todos con el sobre versionado y `seq` de conversación; los frames binarios SHALL NOT consumir `seq` ni entrar en el búfer de reenvío.

#### Scenario: Reenvío sin audio
- **GIVEN** una respuesta hablada enviada con `tts.chunk.meta` de `seq` 30..33 y el cliente desconectado tras el 31
- **WHEN** el cliente reconecta con `last_seq: 31`
- **THEN** recibe los sobres `seq` 32.. y ningún frame binario reenviado; el audio perdido no se recupera

#### Scenario: Sobre de tts.chunk.meta
- **WHEN** se emite el primer fragmento de la respuesta `m-2` de la conversación `c-1`
- **THEN** el cliente recibe `{"v":1,"type":"tts.chunk.meta","seq":N,"conversation_id":"c-1","message_id":"m-2","payload":{"seq":0,"sentence_index":0}}` seguido inmediatamente de un frame binario

### Requirement: Cancelación de una respuesta hablada
`cancel {message_id}` SHALL interrumpir la síntesis de la respuesta indicada y responder `tts.cancelled {message_id}`; `cancel {task_id}` SHALL seguir cancelando tareas como hasta ahora. Un `cancel` sin `task_id` ni `message_id`, o con un `message_id` sin síntesis en curso, SHALL responder `error {code: "unknown_task"}`.

#### Scenario: Cancelar la voz
- **GIVEN** `tts.start {message_id: "m-2"}` recibido
- **WHEN** el cliente envía `cancel {message_id: "m-2"}`
- **THEN** recibe `tts.cancelled {message_id: "m-2"}`

#### Scenario: Cancelar un mensaje sin síntesis
- **WHEN** el cliente envía `cancel {message_id: "nope"}`
- **THEN** recibe `error {code: "unknown_task"}`
