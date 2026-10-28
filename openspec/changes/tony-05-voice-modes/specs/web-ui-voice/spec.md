# Spec Delta

## Purpose

Define la voz en la interfaz web: botón de micrófono, captura de audio a 16 kHz mono enviada por WebSocket, estados de escucha y transcripción, reproducción continua de la respuesta hablada a 24 kHz, silenciado de la captura mientras suena audio, botón para detener el audio y comportamiento por modo de respuesta.

## ADDED Requirements

### Requirement: Botón de micrófono
La UI SHALL mostrar un botón de micrófono conmutable con `aria-pressed` y `aria-label` en español. Al activarlo SHALL pedir permiso de micrófono, enviar `audio.start {sample_rate: 16000, channels: 1, format: "f32"}` y empezar a capturar; al desactivarlo SHALL enviar `audio.end` y liberar el micrófono. Un permiso denegado SHALL mostrar un aviso en español y dejar el botón desactivado.

#### Scenario: Activar el micrófono
- **GIVEN** la voz disponible y el micrófono inactivo
- **WHEN** el usuario pulsa el botón y concede permiso
- **THEN** se envía `audio.start {sample_rate: 16000, channels: 1, format: "f32"}`, el botón queda con `aria-pressed="true"` y se muestra "Escuchando…"

#### Scenario: Desactivar el micrófono
- **GIVEN** el micrófono activo
- **WHEN** el usuario pulsa el botón
- **THEN** se envía `audio.end`, se detiene la captura y el botón queda con `aria-pressed="false"`

#### Scenario: Permiso denegado
- **WHEN** el navegador deniega el permiso de micrófono
- **THEN** se muestra un aviso en español y no se envía `audio.start`

### Requirement: Micrófono deshabilitado sin voz en el servidor
Cuando `GET /api/health` indique `voice.available: false`, el botón de micrófono SHALL mostrarse deshabilitado con un tooltip (`title`) en español que incluya la razón y el comando `uv sync --extra voice`; un `error {code: "voice_unavailable"}` recibido por WebSocket SHALL producir el mismo estado.

#### Scenario: Servidor sin extra
- **GIVEN** `/api/health` responde `voice: {available: false, reason: "extra tony[voice] no instalado"}`
- **WHEN** se carga la página
- **THEN** el botón de micrófono está deshabilitado y su `title` contiene `uv sync --extra voice`

#### Scenario: Error por WebSocket
- **WHEN** llega `error {code: "voice_unavailable"}`
- **THEN** el botón queda deshabilitado con el tooltip y se muestra el aviso

### Requirement: Captura a 16 kHz mono por frames
La captura SHALL producir PCM Float32 a 16 kHz mono en frames de 20 a 40 ms, re-muestreando en el hilo de audio si el dispositivo trabaja a otra frecuencia, y enviar cada frame como mensaje binario mientras el micrófono esté activo y no haya audio en reproducción. La UI SHALL mostrar un indicador de nivel de entrada mientras captura.

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
- **GIVEN** "Escuchando…" visible
- **WHEN** el cliente deja de detectar nivel durante 700 ms tras habla y aún no ha llegado `stt.final`
- **THEN** se muestra "Transcribiendo…" hasta que llegue `stt.final` o un `error`

### Requirement: Reproducción continua a 24 kHz
La UI SHALL reproducir los frames binarios de `tts.chunk` con un contexto de audio a 24 kHz mediante una cola de buffers programados consecutivamente, sin huecos entre frases, respetando el orden de `tts.chunk.meta.seq`. `tts.end` SHALL dejar que la cola termine; `tts.cancelled` SHALL vaciar la cola y parar el audio inmediatamente.

#### Scenario: Cola sin huecos
- **WHEN** llegan tres `tts.chunk` de 500 ms cada uno
- **THEN** cada buffer se programa para empezar exactamente donde termina el anterior

#### Scenario: Cancelación vacía la cola
- **GIVEN** dos buffers pendientes de reproducir
- **WHEN** llega `tts.cancelled`
- **THEN** la cola queda vacía y no suena ningún buffer pendiente

#### Scenario: Chunk fuera de orden descartado
- **GIVEN** recibido `tts.chunk.meta {seq: 2}`
- **WHEN** llega `tts.chunk.meta {seq: 1}`
- **THEN** su frame se descarta y no se reproduce

### Requirement: Captura silenciada durante la reproducción
Mientras haya audio de respuesta en reproducción (desde `tts.start` hasta `tts.end` o `tts.cancelled`) el cliente SHALL dejar de enviar frames de audio aunque el micrófono siga activo, y SHALL reanudar el envío al terminar. La UI SHALL indicar "Hablando…" durante la reproducción.

#### Scenario: Captura silenciada durante la reproducción
- **GIVEN** el micrófono activo y `tts.start` recibido
- **WHEN** llegan `tts.chunk` y se reproducen
- **THEN** el cliente no envía `audio.chunk` hasta `tts.end` o `tts.cancelled`

#### Scenario: Reanudación
- **GIVEN** la captura silenciada por reproducción
- **WHEN** llega `tts.end` y la cola termina
- **THEN** los frames vuelven a enviarse y se muestra "Escuchando…"

### Requirement: Botón "Detener audio"
Mientras haya audio en reproducción la UI SHALL mostrar un botón "Detener audio" que vacía la cola, para el audio y envía `cancel {message_id}` de la respuesta en curso; el botón SHALL ocultarse al recibir `tts.end` o `tts.cancelled`.

#### Scenario: Detener por botón
- **GIVEN** audio en reproducción del mensaje `m-2`
- **WHEN** el usuario pulsa "Detener audio"
- **THEN** el audio se para, se envía `cancel {message_id: "m-2"}` y el botón desaparece al llegar `tts.cancelled`

### Requirement: Comportamiento por modo de respuesta
En `voice` y `both` la UI SHALL reproducir el audio recibido y mostrar `display_text` completo; en `text` no SHALL reproducir nada. El selector de modo y la etiqueta de cada mensaje SHALL reflejar los cambios hechos por frase (`set_reply_mode`) igual que los hechos por botón.

#### Scenario: Modo voice muestra el texto
- **GIVEN** `user.accepted {effective_mode: "voice"}`
- **WHEN** llegan `tts.*` y `assistant.final {display_text: "| a | b |…"}`
- **THEN** se reproduce el audio y la burbuja muestra la tabla completa renderizada

#### Scenario: Cambio por frase
- **GIVEN** el selector en `auto` y una respuesta hablada
- **WHEN** el usuario dice "respóndeme por escrito", el `front` fija `text` y llega `assistant.final`
- **THEN** la UI consulta los ajustes, marca `text` en el selector y el siguiente `user.accepted.effective_mode` es `text`

### Requirement: Pruebas del frontend de voz
La cola de reproducción, el silenciado de la captura durante `tts.*` y el estado del botón de micrófono SHALL probarse en Vitest con `AudioContext` y `WebSocket` simulados, sin dispositivo de audio real.

#### Scenario: Pruebas sin hardware
- **WHEN** se ejecuta `npm test`
- **THEN** las pruebas de la cola de reproducción y del silenciado pasan en `jsdom` sin micrófono ni altavoz
