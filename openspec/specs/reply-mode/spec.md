# reply-mode Specification

## Purpose
Define cómo se decide el modo de respuesta de cada mensaje (`voice`, `text`, `both`), qué estilo recibe el `front`, el contrato de salida `{display_text, speech_text}` y los avisos de progreso que el canal recibe mientras una tarea delegada sigue en curso.

## Requirements

### Requirement: Prefijo de modo por mensaje
Un mensaje que empiece por `/v `, `/t ` o `/b ` SHALL fijar el modo `voice`, `text` o `both` solo para ese mensaje; el prefijo SHALL eliminarse del texto enviado al `front` y SHALL NOT modificar los ajustes persistidos.

#### Scenario: Prefijo no cambia el modo persistido
- **GIVEN** ajustes con `reply_mode: text`
- **WHEN** el usuario escribe `/v ¿qué tiempo hace?`
- **THEN** la respuesta se produce en modo `voice` con `speech_text`, el texto enviado al `front` es `¿qué tiempo hace?`, los ajustes siguen en `text` y el siguiente mensaje sin prefijo vuelve a `text`

#### Scenario: Prefijo sin texto
- **WHEN** el usuario escribe `/t` sin más texto
- **THEN** no se envía ningún turno y el canal recibe un aviso de que falta el mensaje

### Requirement: Precedencia del modo efectivo
El modo efectivo SHALL resolverse en este orden: prefijo del mensaje > `reply_mode` de los ajustes persistidos > `reply_mode` de la configuración global. `auto` SHALL resolverse a `voice` si la entrada fue audio y a `text` si fue texto. El modo SHALL fijarse al aceptar cada mensaje y no cambiar durante el turno.

#### Scenario: Tabla de precedencia
- **GIVEN** las combinaciones (prefijo, ajustes, configuración, modalidad): (`/v`, `text`, `auto`, texto) → `voice`; (ninguno, `text`, `voice`, audio) → `text`; (ninguno, ausente, `both`, texto) → `both`; (ninguno, ausente, `auto`, texto) → `text`; (ninguno, ausente, `auto`, audio) → `voice`; (ninguno, `auto`, `text`, audio) → `voice`
- **WHEN** se resuelve cada combinación
- **THEN** se obtiene el modo indicado

#### Scenario: Cambio de ajustes durante un turno
- **GIVEN** un turno iniciado en `text`
- **WHEN** `set_reply_mode("voice")` se ejecuta durante ese mismo turno
- **THEN** la respuesta del turno sigue en `text` y el siguiente mensaje se resuelve a `voice`

### Requirement: Estilo inyectado según el modo
El `front` SHALL recibir `style.voice` cuando el modo efectivo es `voice`, `style.text` cuando es `text`, y ambos estilos junto con la instrucción de producir dos versiones cuando es `both`.

#### Scenario: Modo both
- **GIVEN** `style.voice = "Frases cortas"` y `style.text = "Markdown completo"`
- **WHEN** el modo efectivo es `both`
- **THEN** el prompt del turno contiene `Frases cortas`, `Markdown completo` y la instrucción de producir las dos versiones

#### Scenario: Modo text
- **WHEN** el modo efectivo es `text`
- **THEN** el prompt del turno contiene `style.text` y no contiene `style.voice`

### Requirement: Contrato de salida del front
La respuesta del `front` SHALL ser `{display_text: str, speech_text: str | null}` obtenida por salida estructurada. En `text`, `speech_text` SHALL ser `null`; en `voice` y `both`, `speech_text` SHALL ser un resumen hablado sin markdown, tablas ni código y `display_text` SHALL llevar el contenido completo. Si el modelo no devuelve JSON válido, `display_text` SHALL ser el texto plano y `speech_text` `null`.

#### Scenario: Salida válida en voice
- **GIVEN** modo efectivo `voice`
- **WHEN** el modelo devuelve `{"display_text": "| a | b |\n|---|---|", "speech_text": "Dos columnas, a y b"}`
- **THEN** la respuesta tiene ambos campos tal cual

#### Scenario: speech_text forzado a null en text
- **GIVEN** modo efectivo `text`
- **WHEN** el modelo devuelve `{"display_text": "Hola", "speech_text": "Hola"}`
- **THEN** la respuesta tiene `speech_text = null`

#### Scenario: Salida no estructurada
- **WHEN** el modelo termina con el texto `Hola, señor.` sin salida estructurada válida
- **THEN** la respuesta es `{display_text: "Hola, señor.", speech_text: null}`

### Requirement: Frase de espera y progreso
Si una tarea delegada no termina en 3 s, el canal SHALL recibir exactamente una vez `assistant.wait {text: <wait_phrase del front>}` sin ninguna llamada adicional al modelo. Mientras la tarea sigue, cada `task.progress` y cada `task.needs_confirmation` SHALL reenviarse al canal.

#### Scenario: Frase de espera una sola vez
- **GIVEN** una tarea delegada que tarda 10 s
- **WHEN** pasan 3 s sin resultado
- **THEN** el canal recibe exactamente un `assistant.wait` con la `wait_phrase` y después los `task.progress`

#### Scenario: Tarea rápida sin frase
- **GIVEN** una tarea delegada que termina en 1 s
- **WHEN** termina
- **THEN** el canal no recibe ningún `assistant.wait`

#### Scenario: Progreso reenviado
- **GIVEN** una tarea delegada que ejecuta `filesystem.read_file`
- **WHEN** el orquestador emite `task.progress {tool: "filesystem.read_file", step: 1}`
- **THEN** el canal recibe un mensaje de progreso con `filesystem.read_file`
