# Spec Delta

## MODIFIED Requirements

### Requirement: Límite de tamaño de mensaje WebSocket
Un mensaje de texto WebSocket mayor de 32 KiB (32 768 bytes en UTF-8) SHALL rechazarse con `error {code: "message_too_large", detail}` y el cierre de la conexión con código `1009`, sin procesarlo. Un frame binario mayor de 16 KiB (16 384 bytes) SHALL rechazarse con `error {code: "audio_frame_too_large"}` sin cerrar la conexión, y una intervención de audio que supere 30 s de audio acumulado sin fin de frase SHALL cortarse y transcribirse como si hubiera terminado.

#### Scenario: Mensaje demasiado grande
- **WHEN** el cliente envía un `user.text` cuyo sobre JSON ocupa 40 000 bytes
- **THEN** recibe `error {code: "message_too_large"}`, la conexión se cierra con `1009` y no se crea ningún mensaje de usuario

#### Scenario: Mensaje en el límite
- **WHEN** el cliente envía un sobre JSON de exactamente 32 768 bytes
- **THEN** el mensaje se procesa con normalidad

#### Scenario: Frame binario demasiado grande
- **GIVEN** una intervención de audio abierta
- **WHEN** el cliente envía un frame binario de 20 000 bytes
- **THEN** recibe `error {code: "audio_frame_too_large"}`, el frame se descarta y la conexión sigue abierta

#### Scenario: Frame binario en el límite
- **GIVEN** una intervención de audio abierta
- **WHEN** el cliente envía un frame binario de 2 560 bytes (40 ms Float32 a 16 kHz)
- **THEN** el frame se procesa con normalidad

## ADDED Requirements

### Requirement: Disponibilidad de voz en la salud del servidor
`GET /api/health` SHALL incluir `voice: {available: bool, reason: str | null, stt: str, tts: str}` donde `available` es `true` solo si el extra `tony[voice]` está instalado y los alias `voice.stt`/`voice.tts` son válidos; `reason` SHALL explicar en español por qué no está disponible. Comprobar la disponibilidad SHALL NOT cargar ningún modelo.

#### Scenario: Voz disponible
- **GIVEN** el extra instalado y `voice.tts: kokoro/ef_dora`
- **WHEN** llega `GET /api/health`
- **THEN** la respuesta incluye `voice: {available: true, reason: null, stt: "faster-whisper/small", tts: "kokoro/ef_dora"}` y ningún modelo se ha cargado

#### Scenario: Extra ausente
- **GIVEN** el extra no instalado
- **WHEN** llega `GET /api/health`
- **THEN** `voice.available` es `false` y `voice.reason` contiene `uv sync --extra voice`

### Requirement: Cierre ordenado con voz en curso
Al cerrar el servidor, una intervención de audio abierta SHALL descartarse, una síntesis en curso SHALL cancelarse con `tts.cancelled` antes de cerrar el socket con `1001`, y el ejecutor de voz SHALL cerrarse sin esperar a las tareas pendientes, manteniendo el cierre total por debajo de 10 s.

#### Scenario: Ctrl+C durante una respuesta hablada
- **GIVEN** un socket con `tts.start` recibido y frases pendientes
- **WHEN** el proceso recibe `SIGINT`
- **THEN** el socket recibe `tts.cancelled` y se cierra con `1001`, y el proceso sale con código `0` en menos de 10 s
