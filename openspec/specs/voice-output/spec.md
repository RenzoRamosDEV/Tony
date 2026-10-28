# voice-output Specification

## Purpose
Define la salida hablada de una respuesta: segmentación del texto hablado en frases, limpieza de markdown cuando el modelo no produce `speech_text`, streaming de audio por frases mientras el turno sigue, cancelación, degradación a texto cuando falla la síntesis y registro sin audio.

## Requirements

### Requirement: Segmentación en frases
El texto hablado SHALL trocearse en frases en los signos `.`, `?`, `!`, `…` y `;` seguidos de espacio o fin de texto. Un punto SHALL NOT cerrar frase cuando forma parte de una abreviatura (`Sr.`, `Sra.`, `Dr.`, `Dra.`, `p. ej.`, `etc.`, `Ud.`, `núm.`) ni cuando separa decimales (`10.5`) o va dentro de una hora (`10:30`). Los saltos de línea dobles SHALL cerrar frase.

#### Scenario: Tabla de segmentación
- **GIVEN** las entradas `Son las 10:30, señor. Tiene 3 reuniones hoy. La primera, p. ej., a las 11.` → [`Son las 10:30, señor.`, `Tiene 3 reuniones hoy.`, `La primera, p. ej., a las 11.`]; `Cuesta 10.5 euros; es barato.` → [`Cuesta 10.5 euros;`, `es barato.`]; `El Dr. Pérez llega… ¿Le aviso?` → [`El Dr. Pérez llega…`, `¿Le aviso?`]; `Hola\n\nAdiós` → [`Hola`, `Adiós`]
- **WHEN** se segmenta cada entrada
- **THEN** se obtiene la lista indicada

#### Scenario: Texto sin puntuación final
- **WHEN** se segmenta `Buenos días señor`
- **THEN** se obtiene [`Buenos días señor`] al cerrar el flujo

### Requirement: Segmentación incremental
El segmentador SHALL aceptar fragmentos de texto en streaming y emitir cada frase en cuanto quede completa, reteniendo el resto hasta el siguiente fragmento o el cierre del flujo.

#### Scenario: Frase partida entre fragmentos
- **WHEN** llegan los fragmentos `Son las 10` y `:30, señor. Tiene`
- **THEN** tras el segundo fragmento se emite `Son las 10:30, señor.` y `Tiene` queda retenido

#### Scenario: Cierre del flujo
- **GIVEN** `Tiene 3 reuniones` retenido
- **WHEN** se cierra el flujo
- **THEN** se emite `Tiene 3 reuniones` como última frase

### Requirement: Texto hablado cuando falta `speech_text`
Si el modo efectivo es `voice` o `both` y la respuesta no trae `speech_text`, el texto a sintetizar SHALL obtenerse de `display_text` eliminando bloques de código, tablas, encabezados, énfasis, enlaces (conservando su texto) y listas (conservando el texto de cada ítem), truncado a 600 caracteres en un límite de palabra y seguido de ` …te lo muestro en pantalla`.

#### Scenario: Tabla eliminada
- **WHEN** `display_text` es `Aquí tiene la tabla:\n|a|b|\n|1|2|` sin `speech_text`
- **THEN** el texto hablado es `Aquí tiene la tabla: …te lo muestro en pantalla`

#### Scenario: Código y énfasis
- **WHEN** `display_text` es ``Usa **uv**:\n```bash\nuv sync\n```\nListo.`` sin `speech_text`
- **THEN** el texto hablado es `Usa uv: Listo. …te lo muestro en pantalla`

#### Scenario: Truncado a 600 caracteres
- **WHEN** `display_text` tiene 900 caracteres de prosa sin markdown y no hay `speech_text`
- **THEN** el texto hablado tiene ≤ 600 caracteres de prosa cortados en un límite de palabra más el cierre ` …te lo muestro en pantalla`

#### Scenario: Texto corto sin markdown
- **WHEN** `display_text` es `Son las diez.` sin `speech_text`
- **THEN** el texto hablado es `Son las diez.` sin cierre añadido

### Requirement: Streaming de audio por frases
Cuando el modo efectivo es `voice` o `both`, el servidor SHALL emitir `tts.start {message_id}` antes del primer audio, un `tts.chunk.meta {message_id, seq, sentence_index}` seguido de un frame binario PCM Int16 24 kHz mono por cada fragmento sintetizado, en orden de frase y con `seq` creciente desde 0, y `tts.end {message_id}` tras el último fragmento. En `text` SHALL NOT emitirse ningún mensaje `tts.*`.

#### Scenario: Dos frases en orden
- **GIVEN** modo `voice` y `speech_text` `Son las diez. Tiene una reunión.`
- **WHEN** se procesa la respuesta
- **THEN** el cliente recibe `tts.start`, `tts.chunk.meta {seq: 0, sentence_index: 0}`, un frame binario, `tts.chunk.meta {seq: 1, sentence_index: 1}`, un frame binario y `tts.end`, con el mismo `message_id` que `assistant.final`

#### Scenario: Modo text sin audio
- **GIVEN** modo `text`
- **WHEN** se procesa la respuesta
- **THEN** no se recibe ningún `tts.*`

#### Scenario: Modo both
- **GIVEN** modo `both` con `display_text` en markdown y `speech_text` resumido
- **WHEN** se procesa la respuesta
- **THEN** se recibe `assistant.final` con ambos campos y `tts.*` sintetizando solo `speech_text`

### Requirement: Audio antes de terminar el texto
Mientras el `front` entrega fragmentos de texto hablado, cada frase completa SHALL enviarse a síntesis sin esperar al final del turno, de modo que `tts.chunk` pueda llegar antes de `assistant.final`. Cuando el motor no entrega fragmentos, la síntesis SHALL empezar al recibir la respuesta completa y `assistant.final` SHALL enviarse sin esperar a `tts.end`.

#### Scenario: Motor con fragmentos
- **GIVEN** un `front` de prueba que entrega los fragmentos `Son las diez. ` y `Tiene una reunión.`
- **WHEN** se procesa el turno
- **THEN** el primer `tts.chunk.meta` llega antes de `assistant.final`

#### Scenario: Motor sin fragmentos
- **GIVEN** un `front` que solo devuelve la respuesta completa
- **WHEN** se procesa el turno
- **THEN** `assistant.final` llega antes de `tts.end` y todos los `tts.chunk` llegan después de `tts.start`

### Requirement: Cancelación de la síntesis
`cancel` del cliente, una nueva intervención del usuario (`audio.start` o `user.text`) o el cierre de la sesión SHALL interrumpir la síntesis en curso, descartar las frases pendientes y emitir `tts.cancelled {message_id}` en lugar de `tts.end`.

#### Scenario: Cancelación por el usuario
- **GIVEN** `tts.start` recibido y tres frases pendientes
- **WHEN** el cliente envía `cancel {message_id}`
- **THEN** recibe `tts.cancelled {message_id}`, ningún `tts.chunk.meta` posterior y ningún `tts.end`

#### Scenario: Nueva intervención cancela
- **GIVEN** audio en reproducción con frases pendientes
- **WHEN** el cliente envía `audio.start`
- **THEN** recibe `tts.cancelled` antes de que se procese la nueva intervención

### Requirement: Degradación cuando falla la síntesis
Si la síntesis de una frase falla, el servidor SHALL emitir `tts.cancelled {message_id}` y `error {code: "tts_failed", detail}`, descartar las frases restantes y completar el turno en texto: `assistant.final` SHALL enviarse igualmente con el texto completo.

#### Scenario: Fallo en la segunda frase
- **GIVEN** modo `voice` y un sintetizador que lanza una excepción en la segunda frase
- **WHEN** el servidor lo detecta
- **THEN** emite `tts.cancelled` y `error {code: "tts_failed"}`, `assistant.final` llega igualmente y la conexión sigue abierta

#### Scenario: Fallo al cargar el motor
- **GIVEN** modo `voice` y un motor de síntesis que falla al cargar
- **WHEN** se procesa la respuesta
- **THEN** se emite `error {code: "tts_failed"}` sin `tts.start` y `assistant.final` llega con el texto completo

### Requirement: Registro de la síntesis
Al terminar o cancelar la síntesis de una respuesta, el JSONL de la sesión SHALL registrar `tts {sentences, duration_ms, cancelled}` con el número de frases sintetizadas y la duración del audio generado, nunca el audio ni el texto.

#### Scenario: Evento tts
- **WHEN** se sintetizan 2 frases que suman 3 200 ms de audio
- **THEN** el JSONL contiene `tts {sentences: 2, duration_ms: 3200, cancelled: false}` sin campo de texto ni de audio

### Requirement: Secretos nunca se pronuncian
El texto hablado, tanto de la respuesta completa como de sus fragmentos, SHALL redactarse con los secretos del entorno antes de llegar al sintetizador, frase a frase para cubrir secretos partidos entre fragmentos, y la marca de redacción SHALL pronunciarse como «dato oculto».

#### Scenario: Secreto en la respuesta
- **GIVEN** un secreto conocido presente en `speech_text` o partido entre dos fragmentos hablados
- **WHEN** se sintetiza la respuesta
- **THEN** el sintetizador nunca recibe el secreto ni `***`, sino «dato oculto»

### Requirement: Un trabajo de síntesis a la vez
El motor de síntesis SHALL ejecutar una frase a la vez: tras cancelar una síntesis bloqueada en el motor, la siguiente SHALL esperar a que la anterior termine realmente, y la cancelación SHALL comprobarse antes de pedir cada fragmento. La transcripción SHALL poder ejecutarse mientras tanto.

#### Scenario: Síntesis cancelada aún en curso
- **GIVEN** una síntesis cancelada bloqueada dentro del motor
- **WHEN** empieza la síntesis de otra respuesta
- **THEN** esta no entra en el motor hasta que la anterior devuelve el control y una transcripción se completa entretanto
