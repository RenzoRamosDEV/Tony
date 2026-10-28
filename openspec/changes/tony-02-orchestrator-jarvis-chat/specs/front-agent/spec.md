# Spec Delta

## Purpose

Define cómo Tony ejecuta al agente `front` (Jarvis por defecto) como interlocutor único del usuario: sesión conversacional persistente, contexto inyectado en cada turno, tools nativas, criterio para delegar en el `worker` y aislamiento del `worker` respecto al canal.

## ADDED Requirements

### Requirement: Sesión conversacional persistente
El agente `front` SHALL ejecutarse en modo conversación: una sesión de chat SHALL mantener un identificador de sesión estable y el historial del modelo entre turnos, sin reiniciar el motor en cada mensaje. Las tools integradas del entorno SHALL seguir deshabilitadas igual que para el `worker`.

#### Scenario: Historial entre turnos
- **GIVEN** una sesión en la que el usuario dijo `me llamo Renzo`
- **WHEN** en el turno siguiente pregunta `¿cómo me llamo?`
- **THEN** el prompt del segundo turno se envía a la misma sesión (mismo identificador) y el modelo dispone del turno anterior

#### Scenario: Opciones seguras del front
- **GIVEN** el agente `jarvis` con `native: ["delegate", "remember", "set_reply_mode"]`
- **WHEN** se construyen las opciones de la sesión
- **THEN** `tools = []`, las tools integradas figuran como no permitidas, `permission_mode = "default"`, `setting_sources = []`, `allowed_tools` incluye `mcp__tony__*`, el modelo es el ID resuelto desde `models` y `output_format` es el esquema de `{display_text, speech_text}`

### Requirement: Contexto dinámico del turno
En cada turno, el prompt efectivo del `front` SHALL incluir el cuerpo de `agent.md` más la fecha y hora local con zona, el modo de respuesta efectivo con su `style`, el bloque de preferencias del usuario (releído del fichero en ese turno) y el catálogo de tools nativas disponibles.

#### Scenario: Preferencia editada a mano
- **GIVEN** una sesión abierta y el usuario añade a mano la línea `- [2026-10-28] Prefiere respuestas cortas` a `memory/preferences.md`
- **WHEN** envía el siguiente mensaje sin reiniciar
- **THEN** el prompt de ese turno contiene `Prefiere respuestas cortas`

#### Scenario: Modo y estilo del turno
- **GIVEN** `style.voice = "Frases cortas, sin markdown"` y un turno con modo efectivo `voice`
- **WHEN** se construye el prompt del turno
- **THEN** contiene `voice` como modo efectivo y la instrucción `Frases cortas, sin markdown`

### Requirement: Sin MCPs salvo declaración explícita
El `front` SHALL NOT tener acceso a ningún servidor MCP salvo los que declare su propio `tool.json`; en ese caso sus tools SHALL pasar por la misma barrera de ejecución (`allow`, confirmación, timeout, log) que las del `worker`.

#### Scenario: Front sin mcpServers
- **GIVEN** `agents/jarvis/tool/tool.json` sin `mcpServers`
- **WHEN** se construyen las opciones de la sesión
- **THEN** el único servidor MCP visible para el modelo es `tony`

#### Scenario: Front con MCP declarado
- **GIVEN** un `front` cuyo `tool.json` declara el servidor `fake` con `allow: ["fake.echo"]`
- **WHEN** se construyen las opciones de la sesión
- **THEN** el modelo ve `mcp__tony__*` y `mcp__fake__echo`, y `mcp__fake__destroy` no está disponible

### Requirement: Tools nativas del servidor `tony`
Las tools nativas SHALL exponerse en el servidor MCP en proceso `tony` (`mcp__tony__<nombre>`) y SHALL ser exactamente las listadas en `tool.json.native` del agente. `delegate(objetivo, contexto="", restricciones=[])` SHALL enviar la tarea al orquestador y esperar su `TaskResult` sin el límite de 20 s de las tools MCP (solo el de la tarea), devolviéndolo serializado.

#### Scenario: Catálogo nativo según tool.json
- **GIVEN** `native: ["remember"]`
- **WHEN** se construye el servidor `tony`
- **THEN** expone `remember` y no expone `delegate` ni `set_reply_mode`

#### Scenario: Delegate devuelve el resultado
- **GIVEN** el `front` llama a `delegate("lista los .md de ~/notas")`
- **WHEN** la tarea termina con `{status: "ok", resumen: "3 ficheros", datos: ["a.md", "b.md", "c.md"], pasos: [...], errores: []}`
- **THEN** el modelo recibe ese `TaskResult` serializado como JSON

#### Scenario: Delegate sin límite de 20 s
- **GIVEN** `tool_timeout_s = 1` y una tarea delegada que tarda 2 s
- **WHEN** el `front` llama a `delegate`
- **THEN** la llamada espera los 2 s y devuelve el resultado, sin error de timeout

#### Scenario: Delegate con cola llena
- **GIVEN** la cola del orquestador está llena
- **WHEN** el `front` llama a `delegate`
- **THEN** recibe `{status: "error", resumen: ..., errores: ["queue_full"]}` sin excepción

### Requirement: Tool nativa `remember`
`remember(texto)` SHALL añadir la línea `- [YYYY-MM-DD] texto` al fichero de preferencias con escritura atómica y SHALL devolver una confirmación en español que incluya el texto guardado.

#### Scenario: Línea añadida
- **GIVEN** el fichero contiene `- [2026-10-28] Prefiere respuestas cortas`
- **WHEN** el `front` llama a `remember("Llamarle \"señor\"")` el 28-10-2026
- **THEN** el fichero termina con `- [2026-10-28] Llamarle "señor"` y la línea anterior se conserva

### Requirement: Tool nativa `set_reply_mode`
`set_reply_mode(modo)` SHALL aceptar únicamente `auto`, `voice`, `text` o `both`, persistir el valor en los ajustes y devolver el modo nuevo; un valor fuera del conjunto SHALL devolver un error sin modificar los ajustes.

#### Scenario: Modo persistido
- **WHEN** el `front` llama a `set_reply_mode("text")`
- **THEN** `memory/settings.json` contiene `{"reply_mode": "text"}` y la tool devuelve `text`

#### Scenario: Modo inválido
- **GIVEN** ajustes con `reply_mode: text`
- **WHEN** el `front` llama a `set_reply_mode("loud")`
- **THEN** la tool devuelve un error que lista los valores permitidos y los ajustes siguen en `text`

### Requirement: Criterio de delegación
El prompt del `front` SHALL instruirle a responder directamente a conversación, preguntas de conocimiento general, hora y fecha (inyectadas) y preferencias, y a llamar a `delegate` cuando la petición requiera datos externos, ficheros, acciones o herramientas. Un `front` sin `delegate` en `native` SHALL responder siempre por sí mismo.

#### Scenario: Pregunta de hora no delega
- **GIVEN** un runner conversacional de prueba que responde sin invocar tools cuando el prompt contiene la hora
- **WHEN** el usuario escribe `¿Qué hora es?`
- **THEN** no se emite ningún `task.queued` y la respuesta contiene la hora inyectada

#### Scenario: Petición de datos externos delega
- **WHEN** el usuario escribe `lista los PRs abiertos`
- **THEN** se emite exactamente un `task.queued` cuyo `objetivo` contiene `PRs abiertos`

#### Scenario: Front sin delegate
- **GIVEN** `native: ["remember"]`
- **WHEN** el usuario escribe `lista los PRs abiertos`
- **THEN** no se emite `task.queued` y el `front` responde por sí mismo

### Requirement: Aislamiento del worker respecto al canal
El `worker` SHALL recibir únicamente un sumidero de eventos que escribe en el log JSONL y en el orquestador; SHALL NOT recibir ninguna referencia al canal. El contenido de un `TaskResult` SHALL llegar al usuario solo como parte de la respuesta redactada por el `front`.

#### Scenario: Dependencias del camino del worker
- **WHEN** se analizan las importaciones de los módulos del runner y del orquestador
- **THEN** ninguno importa el paquete de canales

#### Scenario: Resultado solo vía front
- **GIVEN** una tarea delegada que termina con `resumen: "3 ficheros"`
- **WHEN** se inspeccionan los mensajes enviados al canal durante el turno
- **THEN** no hay ningún mensaje con el `TaskResult` crudo; el único texto de respuesta es el `display_text` del `front`
