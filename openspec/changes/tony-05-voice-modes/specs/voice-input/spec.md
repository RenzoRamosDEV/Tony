# Spec Delta

## Purpose

Define la entrada de voz por WebSocket: apertura y cierre de una intervención de audio, frames binarios, segmentación por detección de voz en el servidor, transcripción, entrega de `stt.final` procesado como un mensaje de texto del usuario, límites de concurrencia y tamaño, y privacidad del audio.

## ADDED Requirements

### Requirement: Apertura de una intervención de audio
`audio.start {sample_rate: 16000, channels: 1, format: "f32"}` SHALL abrir una intervención de audio en la conversación del socket. Un `audio.start` con parámetros distintos SHALL responder `error {code: "unsupported_audio"}`; un `audio.start` mientras otra intervención está abierta SHALL responder `error {code: "audio_in_progress"}`; un `audio.start` sin voz disponible SHALL responder `error {code: "voice_unavailable", detail}`.

#### Scenario: Apertura aceptada
- **GIVEN** un `hello` aceptado y la voz disponible
- **WHEN** el cliente envía `audio.start {sample_rate: 16000, channels: 1, format: "f32"}`
- **THEN** no recibe ningún error y los frames binarios siguientes se aceptan

#### Scenario: Parámetros no soportados
- **WHEN** el cliente envía `audio.start {sample_rate: 44100, channels: 2, format: "f32"}`
- **THEN** recibe `error {code: "unsupported_audio"}` y no se abre ninguna intervención

#### Scenario: Voz no disponible
- **GIVEN** el extra `tony[voice]` no instalado
- **WHEN** el cliente envía `audio.start`
- **THEN** recibe `error {code: "voice_unavailable"}` con un detalle que indica `uv sync --extra voice`

#### Scenario: Segunda intervención simultánea
- **GIVEN** una intervención abierta
- **WHEN** el cliente envía otro `audio.start`
- **THEN** recibe `error {code: "audio_in_progress"}` y la primera sigue abierta

### Requirement: Frames de audio binarios
Tras `audio.start`, cada frame binario WebSocket SHALL contener PCM Float32 a 16 kHz mono de entre 20 y 40 ms (320 a 640 muestras). Un frame binario recibido sin intervención abierta SHALL ignorarse y responder `error {code: "audio_not_started"}` sin cerrar la conexión.

#### Scenario: Frame fuera de intervención
- **GIVEN** un `hello` aceptado y sin `audio.start`
- **WHEN** llega un frame binario
- **THEN** el cliente recibe `error {code: "audio_not_started"}`, el frame se descarta y la conexión sigue abierta

#### Scenario: Frame tras audio.end
- **GIVEN** una intervención cerrada con `audio.end`
- **WHEN** llega un frame binario
- **THEN** el cliente recibe `error {code: "audio_not_started"}`

### Requirement: Segmentación en el servidor y transcripción
El servidor SHALL alimentar el detector de voz con cada frame y, por cada intervención completa (silencio ≥ 700 ms, corte a 30 s o `audio.end` con habla pendiente ≥ 300 ms), transcribirla y emitir `stt.final {text, message_id}`. `stt.partial` SHALL NOT emitirse en la versión 1 del protocolo.

#### Scenario: Intervención por silencio
- **GIVEN** una intervención abierta
- **WHEN** llegan frames con 1,5 s de habla y 700 ms de silencio
- **THEN** el cliente recibe `stt.final {text, message_id}` sin esperar a `audio.end`

#### Scenario: audio.end cierra lo pendiente
- **GIVEN** 1 s de habla sin silencio posterior
- **WHEN** el cliente envía `audio.end`
- **THEN** la intervención pendiente se transcribe y se emite `stt.final`

#### Scenario: Transcripción vacía
- **WHEN** la transcripción de una intervención es vacía
- **THEN** no se emite `stt.final` ni se inicia ningún turno

### Requirement: `stt.final` se procesa como `user.text`
El texto de cada `stt.final` SHALL procesarse exactamente como un `user.text {text}` con modalidad de entrada `audio`: respeta los prefijos `/v`, `/t`, `/b`, emite `user.accepted {message_id, effective_mode}` con el mismo `message_id` del `stt.final`, persiste el mensaje de usuario en el historial y ejecuta el turno del `front`. Si hay un turno en curso, la transcripción SHALL responder `error {code: "turn_in_progress"}` y descartarse.

#### Scenario: Secuencia de una respuesta por voz
- **GIVEN** `reply_mode: "auto"` y un `front` de prueba que responde `{display_text: "Son las diez y media.", speech_text: "Son las diez y media."}`
- **WHEN** el cliente envía `audio.start`, frames con habla, silencio y `audio.end` y el transcriptor devuelve `¿qué hora es?`
- **THEN** recibe, en orden, `stt.final {text: "¿qué hora es?"}`, `user.accepted {effective_mode: "voice"}`, `assistant.final` (el motor sin fragmentos entrega la respuesta completa antes de sintetizar), `tts.start`, `tts.chunk.meta {seq: 0, sentence_index: 0}`, un frame binario y `tts.end`, todos los `tts.*` con el `message_id` de `assistant.final`

#### Scenario: Transcripción con prefijo
- **GIVEN** `reply_mode: "auto"`
- **WHEN** el transcriptor devuelve `/t qué hora es`
- **THEN** `user.accepted.effective_mode` es `text` y el mensaje persistido es `qué hora es`

#### Scenario: Turno en curso
- **GIVEN** un turno iniciado y sin `assistant.final`
- **WHEN** llega un `stt.final`
- **THEN** el cliente recibe `error {code: "turn_in_progress"}` y la transcripción no se envía al `front`

### Requirement: Una intervención de audio a la vez y cierre
`audio.end` SHALL cerrar la intervención abierta y liberar el estado del detector; un `audio.end` sin intervención abierta SHALL responder `error {code: "audio_not_started"}`. Al cerrarse el socket, la intervención abierta SHALL descartarse sin transcribir.

#### Scenario: Cierre normal
- **GIVEN** una intervención abierta sin habla pendiente
- **WHEN** el cliente envía `audio.end`
- **THEN** no se emite `stt.final` y un nuevo `audio.start` se acepta

#### Scenario: Socket cerrado con intervención abierta
- **GIVEN** una intervención abierta con 1 s de habla
- **WHEN** el socket se cierra
- **THEN** no se transcribe nada ni se emite `stt.final` tras la reconexión

### Requirement: Privacidad del audio de entrada
El audio del usuario SHALL vivir solo en memoria: nunca SHALL escribirse en disco ni en SQLite; solo la transcripción se persiste como mensaje de usuario. El registro JSONL de la sesión SHALL anotar `stt.final {chars, duration_ms}` y nunca el audio ni el texto transcrito.

#### Scenario: Solo la transcripción se persiste
- **WHEN** se completa una intervención transcrita como `¿qué hora es?`
- **THEN** el historial contiene el mensaje de usuario `¿qué hora es?` y no existe ningún fichero de audio nuevo bajo `logs/`, `memory/` ni el directorio temporal

#### Scenario: Evento de log sin contenido
- **WHEN** se emite `stt.final` con 13 caracteres y 1 500 ms de audio
- **THEN** el JSONL de la sesión contiene `stt.final {chars: 13, duration_ms: 1500}` sin campo `text`
