# agent-runner Specification

## Purpose
Define cómo Tony ejecuta un agente `worker` sobre un modelo de lenguaje: el contrato de entrada/salida estructurado, qué tools puede usar el agente, la barrera única de ejecución y los eventos y estados de fin de tarea.

## Requirements

### Requirement: Contrato de tarea estructurado
Una ejecución SHALL recibir un `TaskRequest {objetivo: str, contexto: str, restricciones: list[str]}` y SHALL devolver un `TaskResult {status: ok|partial|error|cancelled|timeout, resumen: str, datos: dict|list|str|null, pasos: list[str], errores: list[str]}`. El prompt de usuario SHALL ser el `TaskRequest` serializado en JSON precedido de la instrucción de devolver un `TaskResult`.

#### Scenario: Salida estructurada válida
- **GIVEN** el modelo devuelve una salida estructurada que valida contra el esquema de `TaskResult` con `status: ok`
- **WHEN** termina la ejecución
- **THEN** el `TaskResult` devuelto es exactamente esa salida

#### Scenario: Salida estructurada ausente o inválida
- **GIVEN** el modelo termina con texto final `He listado los ficheros.` y sin salida estructurada válida
- **WHEN** termina la ejecución
- **THEN** el `TaskResult` es `{status: "partial", resumen: "He listado los ficheros.", datos: null, pasos: [], errores: ["respuesta no estructurada"]}`

### Requirement: System prompt con contexto de ejecución
El system prompt efectivo SHALL ser el cuerpo de `agent.md` seguido de un bloque de contexto con la fecha y hora local (con zona horaria), el rol del agente y las `restricciones` de la tarea, y, si el agente tiene skills, del índice `Skills disponibles:` con una línea `- <name>: <description>` por skill y sin ningún cuerpo.

#### Scenario: Bloque de contexto
- **GIVEN** un agente con `system_prompt = "Eres Viernes."` y una tarea con `restricciones: ["no escribas ficheros"]`
- **WHEN** se construyen las opciones de ejecución
- **THEN** el system prompt empieza por `Eres Viernes.`, contiene la fecha/hora local con zona, el rol `worker` y la línea `no escribas ficheros`

#### Scenario: Índice de skills del worker
- **GIVEN** un `worker` con la skill `resumen-web` (descripción `Resume una página web`)
- **WHEN** se construyen las opciones de ejecución
- **THEN** el system prompt contiene `Skills disponibles:` y `- resumen-web: Resume una página web`, y no contiene el cuerpo de la skill

### Requirement: Tools integradas deshabilitadas
El agente SHALL NOT tener acceso a las tools integradas del entorno de ejecución (Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch, Task y similares) ni a configuración del usuario del entorno: la lista de tools base SHALL ser vacía, las tools integradas SHALL figurar como no permitidas, SHALL NOT cargarse fuentes de configuración externas, el modo de permisos SHALL ser `default` (nunca `bypassPermissions`) y toda solicitud de tool cuyo nombre no empiece por `mcp__` SHALL ser denegada.

#### Scenario: Opciones de ejecución seguras
- **GIVEN** un agente con el servidor MCP `fs` permitido
- **WHEN** se construyen las opciones de ejecución
- **THEN** `tools = []`, `disallowed_tools` incluye `Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, `WebSearch` y `Task`, `allowed_tools = ["mcp__fs__*"]`, `permission_mode = "default"`, `setting_sources = []`, `max_turns = max_steps` del agente, `model` es el ID resuelto desde `models` y `output_format` es el esquema JSON de `TaskResult`

#### Scenario: Denegación de tool integrada
- **GIVEN** el modelo solicita la tool `Bash`
- **WHEN** se evalúa el permiso
- **THEN** la solicitud es denegada y no se ejecuta

#### Scenario: Denegación de tool fuera del catálogo
- **GIVEN** `allow: ["fs.read_file"]` y el modelo solicita `mcp__fs__write_file`
- **WHEN** se evalúa el permiso
- **THEN** la solicitud es denegada y nunca llega al servidor

### Requirement: Proxies MCP como única barrera de ejecución
Por cada servidor MCP del catálogo, el agente SHALL ver un servidor MCP en proceso con el mismo nombre cuyas tools son proxies con el nombre, descripción y esquema de entrada originales. Cada proxy SHALL aplicar en orden: comprobación de cancelación de la tarea → comprobación de `allow` → confirmación si procede → ejecución con timeout → registro en el log. Una tarea cancelada SHALL NOT ejecutar ninguna tool más.

#### Scenario: Nombre visible para el modelo
- **GIVEN** el catálogo contiene `fs.read_file`
- **WHEN** se construyen los servidores en proceso
- **THEN** el modelo ve la tool `mcp__fs__read_file` con la descripción y el esquema de entrada de `read_file`

#### Scenario: Llamada a través del proxy
- **GIVEN** el modelo invoca `mcp__fake__echo` con `{text: "hola"}`
- **WHEN** el proxy la procesa
- **THEN** se emite `tool.call`, se ejecuta `fake.echo` en el servidor real, se emite `tool.result` con `ok = true` y el modelo recibe `hola`

#### Scenario: Barrera de cancelación
- **GIVEN** la tarea ya está marcada como cancelada
- **WHEN** el modelo invoca `mcp__fake__echo`
- **THEN** el proxy devuelve el error `Tarea cancelada` sin llamar al servidor, sin solicitar confirmación y con `tool.result {ok: false}` en el log

### Requirement: Eventos de progreso
Durante la ejecución el sistema SHALL emitir, en orden, `task.started`, `tool.call {tool, args}` y `tool.result {ok, duration_ms, error}` por cada llamada, `assistant.text {text}` por cada fragmento de texto y `task.finished {status, usage: {input_tokens, output_tokens, total_cost_usd, num_turns}}` al terminar.

#### Scenario: Secuencia mínima
- **GIVEN** una tarea que ejecuta una tool y termina con `ok`
- **WHEN** termina la ejecución
- **THEN** los eventos emitidos son `task.started`, `tool.call`, `tool.result`, `task.finished` (con posibles `assistant.text` intercalados) y `task.finished.status = ok`

### Requirement: Timeout y errores de tarea
Si la tarea supera `limits.task_timeout_s` (300 s) desde su inicio, incluyendo la conexión del motor y las esperas de confirmación, el `TaskResult` SHALL tener `status = "timeout"`. Una cancelación externa SHALL interrumpir el motor y producir `status = "cancelled"` con el motivo recibido en `errores`. Cualquier excepción del motor SHALL producir `status = "error"` con el mensaje en `errores`, sin trazas para el usuario.

#### Scenario: Timeout de tarea
- **GIVEN** `task_timeout_s = 1` y un agente que no termina
- **WHEN** transcurre 1 s
- **THEN** la ejecución se interrumpe y el `TaskResult` tiene `status = "timeout"` y `task.finished.status = timeout`

#### Scenario: Timeout durante la conexión
- **GIVEN** `task_timeout_s = 0.2` y un motor cuya conexión tarda 2 s
- **WHEN** transcurren 0,2 s
- **THEN** el `TaskResult` tiene `status = "timeout"` sin esperar a que termine la conexión

#### Scenario: Cancelación externa
- **GIVEN** una ejecución en curso
- **WHEN** se cancela desde fuera con motivo `user`
- **THEN** se llama a la interrupción del motor, el `TaskResult` tiene `status = "cancelled"`, `errores` contiene `cancelada por el usuario` y `task.finished.status = cancelled`

#### Scenario: Excepción del motor
- **GIVEN** el motor de ejecución lanza una excepción `connection refused`
- **WHEN** termina la ejecución
- **THEN** el `TaskResult` tiene `status = "error"` y `errores` contiene `connection refused`, y la salida al usuario no contiene traza de pila

### Requirement: Servidor nativo `tony` del worker
Cuando `tool.json.native` del `worker` incluye `read_skill` o `run_subagent`, las opciones de ejecución SHALL incluir el servidor MCP en proceso `tony` con exactamente esas tools y `allowed_tools` SHALL incluir `mcp__tony__*`; sin tools nativas declaradas SHALL NOT existir el servidor `tony`. Las tools nativas SHALL NOT pasar por el límite de 20 s de las tools MCP.

#### Scenario: Worker con tools nativas
- **GIVEN** un `worker` con `native: ["read_skill", "run_subagent"]` y el servidor MCP `fs`
- **WHEN** se construyen las opciones de ejecución
- **THEN** `mcp_servers` contiene `tony` y `fs`, `allowed_tools` es `["mcp__fs__*", "mcp__tony__*"]` y el servidor `tony` expone `read_skill` y `run_subagent`

#### Scenario: Worker sin tools nativas
- **GIVEN** un `worker` con `native: []`
- **WHEN** se construyen las opciones de ejecución
- **THEN** `mcp_servers` no contiene `tony`

### Requirement: Skills activadas en la petición del worker
Si `objetivo` o `contexto` de la tarea contienen alguna frase de `trigger` de una skill del `worker` (sin distinguir mayúsculas ni acentos), la petición enviada al modelo SHALL incluir el bloque `<skill name="…">…</skill>` correspondiente antes del `TaskRequest` serializado.

#### Scenario: Trigger en el objetivo
- **GIVEN** un `worker` con la skill `resumen-web` (trigger `resume esta web`)
- **WHEN** se construye la petición para `TaskRequest {objetivo: "Resume esta web: https://x.y"}`
- **THEN** la petición contiene `<skill name="resumen-web">` seguido del `TaskRequest` en JSON

#### Scenario: Sin trigger
- **WHEN** se construye la petición para `TaskRequest {objetivo: "lista los ficheros"}`
- **THEN** la petición no contiene `<skill`

### Requirement: Eventos de subtarea en el runner
Cuando el `worker` ejecuta `run_subagent`, el runner SHALL emitir `tool.call {tool: "tony.run_subagent", args}` y `tool.result {ok, duration_ms, error}` como para cualquier otra tool, de modo que el progreso y el log reflejen la llamada.

#### Scenario: Llamada registrada
- **GIVEN** un `worker` que llama a `run_subagent("investigador", "x")`
- **WHEN** la subtarea termina con `status: ok`
- **THEN** el log del padre contiene `tool.call {tool: "tony.run_subagent", args: {nombre: "investigador", objetivo: "x", ...}}` y `tool.result {ok: true}`

### Requirement: Motor efectivo del `worker` determina la implementación

La ejecución de una tarea del `worker` SHALL usar la implementación de `AgentRunner` correspondiente al motor efectivo del agente (`claude_sdk` o un perfil `litellm`), manteniendo sin cambios el contrato `TaskRequest`/`TaskResult`, la barrera única de ejecución de tools y la secuencia de eventos de progreso, cualquiera que sea el motor.

#### Scenario: Eventos de progreso iguales entre motores
- **WHEN** la misma tarea se ejecuta una vez con `engine: claude_sdk` y otra con `engine: litellm`
- **THEN** ambas ejecuciones emiten `task.started`, `tool.call`, `tool.result` y `task.finished` en el mismo orden y con los mismos campos
