# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
