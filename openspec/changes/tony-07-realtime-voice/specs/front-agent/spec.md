## MODIFIED Requirements

### Requirement: Sesión conversacional persistente
El agente `front` SHALL ejecutarse en modo conversación: una sesión de chat SHALL mantener un identificador de sesión estable y el historial del modelo entre turnos, sin reiniciar el motor en cada mensaje, con salida parcial en streaming activada y esfuerzo `low`. Las tools integradas del entorno SHALL seguir deshabilitadas igual que para el `worker`.

#### Scenario: Historial entre turnos
- **GIVEN** una sesión en la que el usuario dijo `me llamo Renzo`
- **WHEN** en el turno siguiente pregunta `¿cómo me llamo?`
- **THEN** el prompt del segundo turno se envía a la misma sesión (mismo identificador) y el modelo dispone del turno anterior

#### Scenario: Opciones seguras del front
- **GIVEN** el agente `jarvis` con `native: ["delegate", "remember", "set_reply_mode"]`
- **WHEN** se construyen las opciones de la sesión
- **THEN** `tools = []`, las tools integradas figuran como no permitidas, `permission_mode = "default"`, `setting_sources = []`, `allowed_tools` incluye `mcp__tony__*`, el modelo es el ID resuelto desde `models`, `include_partial_messages = true`, `effort = "low"` y `output_format` es el esquema de `{speech_text, display_text}` con `speech_text` como primera propiedad

## ADDED Requirements

### Requirement: Salida parcial en streaming del front
Durante un turno, el runner del `front` SHALL extraer de forma incremental los campos `speech_text` y `display_text` del JSON parcial de la salida estructurada, decodificando escapes partidos entre fragmentos, e invocar `on_speech` con cada fragmento nuevo de `speech_text` y `on_text` con cada fragmento nuevo de `display_text`; la entrada parcial de otras tools SHALL ignorarse.

#### Scenario: Campos en streaming
- **GIVEN** fragmentos parciales `{"speech_text": "Son las` + ` diez.", "display_text": "Son las **10**` + `."}`
- **WHEN** se consume el turno
- **THEN** `on_speech` recibe `Son las` y ` diez.` y `on_text` recibe `Son las **10**` y `.`, en ese orden

#### Scenario: Escape partido
- **GIVEN** un fragmento que termina en `\` y el siguiente empieza por `"hola\"`
- **WHEN** se extrae `speech_text`
- **THEN** el texto entregado contiene `"hola"` sin barras

#### Scenario: Entrada de otra tool
- **GIVEN** el `front` llama a `delegate` con `{"objetivo": "..."}` antes de responder
- **WHEN** se consume el turno
- **THEN** `on_speech` y `on_text` no reciben nada de la entrada de `delegate`

### Requirement: Respuesta final autoritativa sin parciales
`assistant.final` SHALL seguir construyéndose con la salida estructurada completa del turno. Si el motor no entrega salida parcial, el JSON parcial no se puede interpretar o `speech_text` es nulo, SHALL NOT enviarse ningún fragmento hablado adicional y el comportamiento SHALL ser el de una respuesta sin fragmentos.

#### Scenario: Motor sin parciales
- **GIVEN** un motor del `front` que solo devuelve la respuesta completa
- **WHEN** se procesa un turno en modo `voice`
- **THEN** no se invoca `on_speech` y la síntesis empieza con `assistant.final`

#### Scenario: JSON parcial ilegible
- **GIVEN** fragmentos parciales que no forman un objeto JSON válido
- **WHEN** se consume el turno
- **THEN** la extracción se detiene sin error y `assistant.final` lleva el texto completo de la respuesta final

### Requirement: Estilo hablado de Jarvis
El agente `jarvis` incluido SHALL declarar en `style.voice` y en su prompt un estilo hablado conciso, sereno y preciso, con ironía sutil solo cuando encaje, tratamiento "señor", sin exclamaciones ni entusiasmo excesivo, números redondeados dichos con naturalidad y vocabulario de español latinoamericano neutro sin regionalismos ni peninsularismos.

#### Scenario: Estilo en el prompt del turno
- **GIVEN** el agente `jarvis` incluido y un turno con modo efectivo `voice`
- **WHEN** se construye el prompt del turno
- **THEN** contiene la instrucción de `style.voice` con `señor`, `sereno` y `español latinoamericano neutro`
