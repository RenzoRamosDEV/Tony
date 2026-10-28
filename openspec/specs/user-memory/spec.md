# user-memory Specification

## Purpose
Define la memoria persistente de Tony: las preferencias del usuario editables a mano (`memory/preferences.md`), los ajustes tipados (`memory/settings.json`) y el historial de conversaciones, mensajes y tareas (`memory/conversations.sqlite`).

## Requirements

### Requirement: Directorio de memoria
El sistema SHALL crear el directorio `memory/` si no existe antes de leer o escribir cualquiera de sus ficheros, y un fichero ausente SHALL tratarse como vacío.

#### Scenario: Primer arranque
- **GIVEN** no existe `memory/`
- **WHEN** se lee el fichero de preferencias
- **THEN** el directorio se crea, la lectura devuelve una lista vacía y no se produce error

### Requirement: Preferencias en `preferences.md`
El almacén de preferencias SHALL exponer `read()` (líneas no vacías del fichero, en orden) y `append(text)` que añade `- [YYYY-MM-DD] text` con la fecha local del día mediante escritura atómica (fichero temporal y sustitución), conservando el contenido previo.

#### Scenario: Append conserva contenido
- **GIVEN** el fichero contiene `- [2026-10-28] Prefiere respuestas cortas`
- **WHEN** se llama a `append("Llamarle \"señor\"")` el 28-10-2026
- **THEN** `read()` devuelve `["- [2026-10-28] Prefiere respuestas cortas", "- [2026-10-28] Llamarle \"señor\""]`

#### Scenario: Escritura atómica
- **GIVEN** un fichero con 3 líneas
- **WHEN** `append` falla al sustituir el fichero temporal
- **THEN** el fichero original sigue con sus 3 líneas intactas y no quedan ficheros temporales en `memory/`

#### Scenario: Líneas vacías ignoradas
- **GIVEN** un fichero con una línea, una línea en blanco y otra línea
- **WHEN** se llama a `read()`
- **THEN** devuelve dos elementos

### Requirement: Bloque de inyección con límite
El bloque de preferencias inyectado al `front` SHALL contener todas las líneas si no superan `limits.memory_max_lines` (200). Si lo superan, SHALL contener la cabecera `(…N líneas anteriores omitidas; ejecuta /memoria para verlas)` seguida de las últimas `memory_max_lines` líneas. SHALL NOT resumirse ni borrarse ninguna línea del fichero.

#### Scenario: Bajo el límite
- **GIVEN** 200 líneas
- **WHEN** se construye el bloque
- **THEN** contiene las 200 líneas y ninguna cabecera de omisión

#### Scenario: Sobre el límite
- **GIVEN** 205 líneas
- **WHEN** se construye el bloque
- **THEN** empieza por `(…5 líneas anteriores omitidas; ejecuta /memoria para verlas)` y contiene las líneas 6 a 205; el fichero sigue teniendo 205 líneas

### Requirement: Relectura en cada turno
El fichero de preferencias SHALL releerse en cada turno de conversación, de modo que una edición manual sea visible en el turno siguiente sin reiniciar el proceso.

#### Scenario: Edición manual visible
- **GIVEN** una sesión abierta con el fichero vacío
- **WHEN** se añade a mano `- [2026-10-28] Prefiere respuestas cortas` y el usuario envía el siguiente mensaje
- **THEN** el bloque de preferencias de ese turno contiene esa línea

### Requirement: Ajustes en `settings.json`
El almacén de ajustes SHALL leer `memory/settings.json` de forma tolerante (fichero ausente, vacío o inválido → ajustes vacíos sin excepción), SHALL validar `reply_mode` contra `auto|voice|text|both` y SHALL escribir con escritura atómica un JSON como `{"reply_mode": "text"}`.

#### Scenario: Fichero ausente
- **GIVEN** no existe `memory/settings.json`
- **WHEN** se leen los ajustes
- **THEN** `reply_mode` es `None` y no se produce error

#### Scenario: Fichero corrupto
- **GIVEN** `memory/settings.json` contiene `{not json`
- **WHEN** se leen los ajustes
- **THEN** se obtienen ajustes vacíos y una advertencia en el log, sin excepción

#### Scenario: Escritura
- **WHEN** se guarda `reply_mode = "text"`
- **THEN** el fichero contiene exactamente el objeto `{"reply_mode": "text"}` y una lectura posterior devuelve `text`

#### Scenario: Valor fuera de dominio en fichero
- **GIVEN** `memory/settings.json` contiene `{"reply_mode": "loud"}`
- **WHEN** se leen los ajustes
- **THEN** `reply_mode` es `None` y se registra una advertencia

### Requirement: Esquema del historial en SQLite
El almacén de conversaciones SHALL crear en `memory/conversations.sqlite`, si no existen, las tablas `conversations(id, channel, created_at)`, `messages(id, conversation_id, role, content, reply_mode, created_at)` y `tasks(id, conversation_id, status, request_json, result_json, tokens_in, tokens_out, cost_usd, created_at, finished_at)`.

#### Scenario: Esquema creado al abrir
- **GIVEN** no existe el fichero SQLite
- **WHEN** se abre el almacén
- **THEN** existen las tres tablas con las columnas indicadas

#### Scenario: Reapertura sin pérdida
- **GIVEN** un fichero con una conversación y dos mensajes
- **WHEN** se vuelve a abrir el almacén
- **THEN** la conversación y los mensajes siguen disponibles

### Requirement: Operaciones del historial
El almacén SHALL exponer `start_conversation(channel) -> id`, `add_message(conversation_id, role, content, reply_mode)`, `record_task(...)` con estado, tokens, coste y JSON de petición y resultado, `recent_messages(conversation_id, limit=40)` en orden cronológico y `last_conversation(channel) -> id | None`.

#### Scenario: Mensajes recientes en orden
- **GIVEN** una conversación con 45 mensajes
- **WHEN** se llama a `recent_messages(id)` con el límite por defecto
- **THEN** devuelve los 40 más recientes en orden cronológico ascendente

#### Scenario: Tarea registrada con coste
- **WHEN** se llama a `record_task` con `status = "done"`, `tokens_in = 120`, `tokens_out = 40`, `cost_usd = 0.003` y un `TaskResult`
- **THEN** la fila de `tasks` conserva esos valores, `request_json` y `result_json` son JSON válidos y `finished_at` no es nulo

#### Scenario: Última conversación del canal
- **GIVEN** dos conversaciones del canal `cli` y una del canal `web`
- **WHEN** se llama a `last_conversation("cli")`
- **THEN** devuelve el id de la conversación `cli` más reciente; `last_conversation("voice")` devuelve `None`
