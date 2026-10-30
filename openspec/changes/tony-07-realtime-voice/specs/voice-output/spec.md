## MODIFIED Requirements

### Requirement: Cancelación de la síntesis
`cancel` del cliente, una nueva intervención del usuario (`audio.start`, `user.text` o una interrupción por voz detectada) o el cierre de la sesión SHALL interrumpir la síntesis en curso, descartar las frases y acuses pendientes y emitir `tts.cancelled {message_id}` en lugar de `tts.end`.

#### Scenario: Cancelación por el usuario
- **GIVEN** `tts.start` recibido y tres frases pendientes
- **WHEN** el cliente envía `cancel {message_id}`
- **THEN** recibe `tts.cancelled {message_id}`, ningún `tts.chunk.meta` posterior y ningún `tts.end`

#### Scenario: Nueva intervención cancela
- **GIVEN** audio en reproducción con frases pendientes
- **WHEN** el cliente envía `audio.start`
- **THEN** recibe `tts.cancelled` antes de que se procese la nueva intervención

#### Scenario: Interrupción por voz cancela
- **GIVEN** audio en reproducción con frases pendientes
- **WHEN** el servidor detecta una interrupción por voz
- **THEN** emite `tts.cancelled` y ningún `tts.chunk.meta` posterior de esa respuesta

## ADDED Requirements

### Requirement: Primer fragmento corto
La primera pieza hablada de cada respuesta SHALL cortarse en la primera coma, dos puntos o punto y coma seguidos de espacio si aparece dentro de las primeras 8 palabras, o si no tras la 6.ª palabra completa; las piezas siguientes SHALL seguir la segmentación en frases. Abreviaturas, decimales y horas SHALL respetarse igual que en la segmentación en frases.

#### Scenario: Corte en la coma
- **WHEN** llega en streaming `Buenas tardes, señor. Los sistemas están en línea.`
- **THEN** las piezas son [`Buenas tardes,`, `señor.`, `Los sistemas están en línea.`]

#### Scenario: Sin coma temprana
- **WHEN** llega `La reunión de las cinco con el equipo sigue en pie.`
- **THEN** la primera pieza es `La reunión de las cinco con` y la segunda `el equipo sigue en pie.`

#### Scenario: Decimal no es cláusula
- **WHEN** llega `Cuesta 10,5 euros, señor.`
- **THEN** la primera pieza es `Cuesta 10,5 euros,`

### Requirement: Pausas naturales
Tras cada pieza sintetizada salvo la última, el servidor SHALL añadir silencio PCM: 160 ms tras fin de frase y 80 ms tras un corte de cláusula; nunca SHALL añadir más de 200 ms seguidos.

#### Scenario: Pausa entre frases
- **GIVEN** `speech_text` `Son las diez. Tiene una reunión.`
- **WHEN** se sintetiza
- **THEN** el audio de la primera frase termina con 160 ms de silencio y el de la última no tiene silencio añadido

#### Scenario: Pausa de cláusula
- **GIVEN** la primera pieza `Buenas tardes,`
- **WHEN** se sintetiza
- **THEN** termina con 80 ms de silencio añadido

### Requirement: Acuses pregrabados para delegaciones
En modo `voice` o `both`, cuando el `front` delega una tarea y aún no ha sonado audio de esa respuesta, el servidor SHALL reproducir al instante un acuse de `voice.acknowledgements` (rotando en orden) desde una caché sintetizada una vez por voz, como primera pieza de la respuesta, sin llamar al modelo; si no está listo en la caché, SHALL omitirse sin esperar.

#### Scenario: Acuse inmediato
- **GIVEN** modo `voice`, la caché lista y el `front` que llama a `delegate`
- **WHEN** empieza la delegación
- **THEN** en ≤ 100 ms llegan `tts.start` y el primer `tts.chunk` con el audio de `Un momento, señor.` sin nueva síntesis

#### Scenario: Modo text sin acuse
- **GIVEN** modo `text`
- **WHEN** el `front` delega
- **THEN** no se emite ningún `tts.*`

#### Scenario: Caché sin preparar
- **GIVEN** la caché de acuses aún sintetizándose
- **WHEN** el `front` delega
- **THEN** no se emite acuse y la respuesta se habla normalmente al llegar `speech_text`
