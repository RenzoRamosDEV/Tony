## MODIFIED Requirements

### Requirement: Segmentación en el servidor y transcripción
El servidor SHALL alimentar el detector de voz con cada frame y, por cada intervención completa (silencio ≥ `voice.end_silence_ms`, corte a 30 s de duración acumulada o `audio.end` con ≥ 300 ms de habla pendiente), transcribirla y emitir `stt.final {text, message_id}`. `stt.partial` SHALL NOT emitirse en la versión 1 del protocolo.

#### Scenario: Intervención por silencio
- **GIVEN** una intervención abierta y el silencio de cierre por defecto
- **WHEN** llegan frames con 1,5 s de habla y 500 ms de silencio
- **THEN** el cliente recibe `stt.final {text, message_id}` sin esperar a `audio.end`

#### Scenario: audio.end cierra lo pendiente
- **GIVEN** 1 s de habla sin silencio posterior
- **WHEN** el cliente envía `audio.end`
- **THEN** la intervención pendiente se transcribe y se emite `stt.final`

#### Scenario: Transcripción vacía
- **WHEN** la transcripción de una intervención es vacía
- **THEN** no se emite `stt.final` ni se inicia ningún turno

## ADDED Requirements

### Requirement: Escucha durante la reproducción
Mientras Tony habla (desde `tts.start` hasta `playback.stopped`, `tts.cancelled` o, si el cliente no avisa, el fin estimado del audio enviado más 2 s), el servidor SHALL seguir clasificando los frames recibidos con un umbral de habla estricto (`voice.barge_in_threshold`, 0,8 por defecto) en lugar del normal.

#### Scenario: Umbral estricto mientras suena la voz
- **GIVEN** `tts.start` emitido y sin `playback.stopped`
- **WHEN** llegan frames con probabilidad de habla 0,6
- **THEN** se clasifican como silencio y no abren ninguna intervención

#### Scenario: Fin de la reproducción
- **GIVEN** `tts.end` emitido
- **WHEN** el cliente envía `playback.stopped {message_id}`
- **THEN** los frames siguientes se clasifican con el umbral normal

#### Scenario: Cliente que no avisa
- **GIVEN** 3 s de audio enviados desde `tts.start`, `tts.end` emitido y ningún `playback.stopped`
- **WHEN** pasan 5 s desde el primer `tts.chunk` según el reloj
- **THEN** el servidor vuelve al umbral normal

### Requirement: Detección de interrupción por voz
Mientras Tony habla, cuando una intervención acumule ≥ `voice.barge_in_min_speech_ms` de habla (280 ms por defecto), el servidor SHALL cancelar al instante toda síntesis en curso con `tts.cancelled`, registrar `barge_in {message_id, speech_ms}` en el JSONL sin audio ni texto, y seguir ensamblando esa intervención, que se transcribe y procesa como cualquier otra.

#### Scenario: El usuario habla encima
- **GIVEN** `tts.chunk` fluyendo para `m-2`
- **WHEN** llegan 300 ms de habla con probabilidad 0,9
- **THEN** el cliente recibe `tts.cancelled {message_id: "m-2"}` antes de que termine la intervención y, tras el silencio de cierre, `stt.final` y `user.accepted` de la nueva intervención

#### Scenario: Ruido breve no interrumpe
- **GIVEN** Tony hablando
- **WHEN** llegan 150 ms de habla estricta seguidos de silencio
- **THEN** no se emite `tts.cancelled` y la síntesis continúa

### Requirement: Turno interrumpido por la voz
Si al detectar la interrupción el turno del `front` sigue generando y no hay tareas delegadas activas, el servidor SHALL interrumpirlo sin cancelar tareas; ese turno SHALL terminar con `assistant.final` cuyo `display_text` es lo generado hasta entonces seguido de ` …` (o `(interrumpido)` si no hubo texto), sin `error turn_failed`, y la nueva transcripción SHALL esperar a que termine (máx. 3 s) en lugar de responder `turn_in_progress`.

#### Scenario: Interrupción mientras genera
- **GIVEN** un turno que ha emitido `assistant.delta {text: "Son las"}` y sigue generando
- **WHEN** se detecta una interrupción y después llega `stt.final`
- **THEN** el cliente recibe `assistant.final {display_text: "Son las …"}` sin `error`, y luego `user.accepted` de la nueva transcripción

#### Scenario: Tarea delegada en curso
- **GIVEN** un turno esperando a la tarea delegada `t-9`
- **WHEN** se detecta una interrupción
- **THEN** solo se cancela la síntesis, `t-9` sigue en `running` y la nueva transcripción recibe `error {code: "turn_in_progress"}`

### Requirement: Eco descartado
Una transcripción originada por una interrupción cuyo texto normalizado (minúsculas, sin puntuación ni tildes) tenga ≥ 3 palabras y esté contenido en el texto hablado cancelado SHALL descartarse como eco: no SHALL emitirse `stt.final` ni iniciarse ningún turno, y SHALL registrarse `barge_in.echo {chars}` en el JSONL.

#### Scenario: Tony se oye a sí mismo
- **GIVEN** la síntesis cancelada de `Son las diez y media, señor.`
- **WHEN** la transcripción de la interrupción es `las diez y media`
- **THEN** no se emite `stt.final` ni `user.accepted` y el JSONL contiene `barge_in.echo`

#### Scenario: Pregunta distinta
- **GIVEN** la síntesis cancelada de `Son las diez y media, señor.`
- **WHEN** la transcripción es `para, ¿qué tiempo hace?`
- **THEN** se emite `stt.final` y se procesa como un turno nuevo

### Requirement: Interrupción por voz desactivable
Con `voice.barge_in: false` el servidor SHALL descartar los frames recibidos mientras Tony habla, sin clasificarlos ni responder error, de modo que el comportamiento equivale a silenciar la captura durante la reproducción.

#### Scenario: Barge-in desactivado
- **GIVEN** `voice.barge_in: false` y `tts.chunk` fluyendo
- **WHEN** llegan 1 s de habla
- **THEN** no se emite `tts.cancelled`, no se transcribe nada y no se envía ningún error
