# codex-engine Specification

## Purpose
Define cómo un agente con `engine: codex_cli` ejecuta tareas de una vez y conversaciones de turnos usando el binario `codex` como motor, con el mismo contrato de tools, confirmación y registro que `claude_sdk`.

## Requirements

### Requirement: Ejecución de una tarea sobre Codex CLI

Un `worker` con `engine: codex_cli` SHALL ejecutar su tarea invocando `codex exec [PROMPT] --json --output-schema <esquema de TaskResult>` como subproceso y SHALL devolver un `TaskResult` idéntico en forma al de `claude_sdk`, parseado del evento JSONL final que contiene la salida estructurada.

#### Scenario: Tarea completada con éxito
- **WHEN** `codex exec` termina con una salida estructurada válida según el esquema de `TaskResult`
- **THEN** el `TaskResult` devuelto tiene `status: "ok"` y los campos del esquema poblados desde esa salida

#### Scenario: Salida sin esquema válido
- **WHEN** `codex exec` termina sin producir una salida que cumpla el esquema de `TaskResult`
- **THEN** el `TaskResult` devuelto tiene `status: "error"` con el detalle en `errores`, sin trazas internas del proceso

### Requirement: Pasarela MCP para el catálogo de tools

Para cada tarea, el motor `codex_cli` SHALL levantar un servidor MCP stdio propio (la pasarela) que expone exactamente las mismas tools, nombres, descripciones y esquemas que el catálogo del agente, aplicando en cada llamada la misma barrera que `claude_sdk`: comprobación de cancelación → `allow` → confirmación si procede → ejecución con timeout → registro en el log. `codex exec` SHALL lanzarse con esa pasarela registrada vía `-c mcp_servers.tony.command=...`.

#### Scenario: Llamada a una tool permitida
- **WHEN** Codex invoca una tool del catálogo a través de la pasarela
- **THEN** la pasarela aplica la barrera igual que el proxy en proceso de `claude_sdk` y el resultado llega a Codex como respuesta de la tool MCP

#### Scenario: Llamada a una tool en `confirm`
- **WHEN** Codex invoca una tool listada en `confirm` y no hay confirmación previa pendiente
- **THEN** la pasarela espera la confirmación con el mismo `confirm_timeout_s` que `claude_sdk` antes de ejecutar o de devolver el rechazo

### Requirement: Conversación del front sobre Codex CLI

Un `front` con `engine: codex_cli` SHALL mantener su sesión conversacional reanudando `codex exec resume <session_id> [PROMPT] --json --output-schema <esquema de FrontReply>` en cada turno, usando el `session_id` devuelto por el primer `codex exec` del turno de apertura.

#### Scenario: Segundo turno de una conversación
- **WHEN** ya existe un `session_id` de un turno anterior
- **THEN** el turno siguiente SHALL invocar `codex exec resume <session_id>` con el nuevo prompt en vez de abrir una sesión nueva

### Requirement: Streaming de voz degradado

Un `front` con `engine: codex_cli` SHALL NOT emitir fragmentos parciales de `on_speech` durante el turno; el texto de voz SHALL entregarse completo una vez recibida la respuesta final del turno.

#### Scenario: Turno con reproducción de voz activa
- **WHEN** el canal activo usa voz y el front usa `engine: codex_cli`
- **THEN** la síntesis de voz comienza solo cuando el turno termina, no durante la generación

### Requirement: Comprobaciones de `tony doctor` para `codex_cli`

`tony doctor` SHALL comprobar, para cada perfil `codex_cli` en uso por algún agente, que el binario `codex` existe en el `PATH` y responde a una invocación mínima de diagnóstico; un fallo SHALL reportarse como `✗` con una sugerencia accionable, sin bloquear las demás comprobaciones.

#### Scenario: `codex` no instalado
- **WHEN** ningún agente usa `engine: codex_cli` que resuelva a un perfil declarado, o el binario `codex` no está en el `PATH`
- **THEN** `tony doctor` reporta `✗ codex: no encontrado en PATH` con una sugerencia de instalación, y el código de salida general es `1`
