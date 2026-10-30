## MODIFIED Requirements

### Requirement: Captura a 16 kHz mono por frames
La captura SHALL producir PCM Float32 a 16 kHz mono en frames de 20 a 40 ms, re-muestreando en el hilo de audio si el dispositivo trabaja a otra frecuencia, y enviar cada frame como mensaje binario mientras el micrófono esté activo, también durante la reproducción de la respuesta. La UI SHALL mostrar un indicador de nivel de entrada mientras captura.

#### Scenario: Dispositivo a 48 kHz
- **GIVEN** un dispositivo de entrada a 48 kHz
- **WHEN** se capturan 30 ms de audio
- **THEN** se envía un frame binario de 480 muestras Float32 (16 kHz)

#### Scenario: Indicador de nivel
- **GIVEN** el micrófono activo
- **WHEN** llega audio con energía
- **THEN** el indicador de nivel refleja la energía del último frame

### Requirement: Estados de escucha y transcripción
Con el micrófono activo la UI SHALL mostrar "Escuchando…"; tras detectarse el fin de una intervención y hasta recibir `stt.final` o un `error`, SHALL mostrar "Transcribiendo…". Cada `stt.final` SHALL añadirse como mensaje del usuario con un icono de micrófono y el `effective_mode` del `user.accepted` correspondiente.

#### Scenario: Transcripción mostrada
- **WHEN** llega `stt.final {text: "¿qué hora es?", message_id: "m-1"}` y `user.accepted {message_id: "m-1", effective_mode: "voice"}`
- **THEN** la lista muestra una burbuja de usuario `¿qué hora es?` con icono de micrófono y la etiqueta `voice`

#### Scenario: Estado de transcripción
- **GIVEN** "Escuchando…" visible y sin audio de respuesta sonando
- **WHEN** el cliente deja de detectar nivel durante 500 ms tras habla y aún no ha llegado `stt.final`
- **THEN** se muestra "Transcribiendo…" hasta que llegue `stt.final` o un `error`

### Requirement: Pruebas del frontend de voz
La cola de reproducción, la captura abierta durante `tts.*`, el aviso `playback.stopped` y el estado del botón de micrófono SHALL probarse en Vitest con `AudioContext` y `WebSocket` simulados, sin dispositivo de audio real.

#### Scenario: Pruebas sin hardware
- **WHEN** se ejecuta `npm test`
- **THEN** las pruebas de la cola de reproducción, de la captura durante la reproducción y del aviso de fin pasan en `jsdom` sin micrófono ni altavoz

## REMOVED Requirements

### Requirement: Captura silenciada durante la reproducción
**Reason**: La interrupción por voz exige que el micrófono siga enviando audio mientras Tony habla; el servidor decide con un umbral estricto si es una interrupción.
**Migration**: El cliente envía frames siempre que el micrófono esté activo (ver "Captura abierta durante la reproducción"); con `voice.barge_in: false` el servidor descarta esos frames y el efecto es el mismo que antes.

## ADDED Requirements

### Requirement: Captura abierta durante la reproducción
La captura SHALL pedir el micrófono con `echoCancellation`, `noiseSuppression` y `autoGainControl` activados y SHALL seguir enviando frames desde `tts.start` hasta `tts.end` o `tts.cancelled`; la UI SHALL indicar "Hablando…" durante la reproducción y volver a "Escuchando…" al terminar.

#### Scenario: Frames durante la reproducción
- **GIVEN** el micrófono activo y `tts.start` recibido
- **WHEN** se capturan frames mientras suenan los `tts.chunk`
- **THEN** cada frame se envía como mensaje binario y se muestra "Hablando…"

#### Scenario: Restricciones de captura
- **WHEN** se activa el micrófono
- **THEN** `getUserMedia` recibe `audio` con `channelCount: 1`, `echoCancellation: true`, `noiseSuppression: true` y `autoGainControl: true`

### Requirement: Parada local inmediata
Al recibir `tts.cancelled` o pulsar "Detener audio", el cliente SHALL parar todas las fuentes programadas y vaciar la cola en el mismo ciclo de eventos, sin esperar a que termine el buffer en curso, y descartar los `tts.chunk` de ese `message_id` que lleguen después.

#### Scenario: Interrupción mientras suena
- **GIVEN** un buffer sonando y dos programados del mensaje `m-2`
- **WHEN** llega `tts.cancelled {message_id: "m-2"}`
- **THEN** se llama a `stop()` en las tres fuentes, la amplitud expuesta es 0 y un `tts.chunk` posterior de `m-2` no se programa

### Requirement: Aviso de fin de reproducción
Cuando la cola de un mensaje termina de sonar tras `tts.end`, o se para por `tts.cancelled` o "Detener audio", el cliente SHALL enviar una vez `playback.stopped {message_id}`.

#### Scenario: Cola agotada
- **GIVEN** `tts.end {message_id: "m-2"}` recibido y un buffer aún sonando
- **WHEN** el buffer termina
- **THEN** el cliente envía exactamente un `playback.stopped {message_id: "m-2"}`

#### Scenario: Parada por cancelación
- **GIVEN** audio de `m-2` sonando
- **WHEN** llega `tts.cancelled {message_id: "m-2"}`
- **THEN** el cliente envía `playback.stopped {message_id: "m-2"}` una sola vez
