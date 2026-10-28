# Spec Delta

## Purpose

Define cómo Tony conecta los servidores MCP declarados por un agente, construye el catálogo de tools visible para el agente, ejecuta llamadas con timeout y mantiene la disponibilidad cuando un servidor falla.

## ADDED Requirements

### Requirement: Conexión a servidores stdio y HTTP
El sistema SHALL conectar cada servidor declarado en `mcpServers` usando transporte stdio (`command` + `args` + `env`) o HTTP streamable (`url` + `headers`), con un timeout de conexión de `limits.mcp_connect_timeout_s` (por defecto 10 s), y SHALL poder operar con servidores de ambos transportes a la vez.

#### Scenario: Servidor stdio arranca y lista tools
- **GIVEN** un servidor stdio `fake` que expone `echo`, `fail`, `slow` y `destroy`
- **WHEN** termina el arranque del gestor
- **THEN** el estado de `fake` es `ready` con `tool_count = 4`

#### Scenario: Timeout de conexión
- **GIVEN** un servidor cuyo proceso arranca pero nunca completa la inicialización MCP
- **WHEN** transcurren `mcp_connect_timeout_s` segundos
- **THEN** el estado del servidor es `error` con un mensaje que indica timeout de conexión y el gestor no queda bloqueado

#### Scenario: Filtro de servidores
- **GIVEN** `mcpServers` con `fs` y `notion`
- **WHEN** se arranca el gestor con un filtro que solo incluye `fs`
- **THEN** solo `fs` se conecta y `notion` no aparece en el estado

### Requirement: Catálogo de tools con nombre cualificado
Por cada tool listada por un servidor, el catálogo SHALL contener una referencia con `server`, `name`, `qualified` (`"server.name"`), `description`, `input_schema`, `destructive` (valor de la anotación MCP `destructiveHint`, `false` si ausente) y `needs_confirm`.

#### Scenario: Tool anotada como destructiva
- **GIVEN** el servidor `fake` expone `destroy` con `annotations.destructiveHint = true` y `echo` sin anotaciones
- **WHEN** se construye el catálogo
- **THEN** `fake.destroy` tiene `destructive = true` y `needs_confirm = true`; `fake.echo` tiene `destructive = false` y `needs_confirm = false`

#### Scenario: Tool listada en `confirm`
- **GIVEN** `confirm: ["fake.echo"]` y `echo` sin anotación destructiva
- **WHEN** se construye el catálogo
- **THEN** `fake.echo` tiene `destructive = false` y `needs_confirm = true`

#### Scenario: Esquema de entrada preservado
- **GIVEN** `echo` declara `input_schema` con la propiedad `text: string`
- **WHEN** se construye el catálogo
- **THEN** la referencia `fake.echo` conserva ese `input_schema` sin modificar

### Requirement: Lista blanca `allow`
Si `allow` está presente, el catálogo SHALL contener únicamente las tools cuyo nombre cualificado coincide con algún patrón `fnmatch` de la lista (`servidor.tool` o `servidor.*`); si `allow` está ausente, SHALL contener todas las tools de los servidores declarados.

#### Scenario: `allow` filtra el catálogo
- **GIVEN** `allow: ["fs.read_file"]` y el MCP `fs` expone `read_file` y `write_file`
- **WHEN** se construye el catálogo
- **THEN** solo `fs.read_file` existe; `fs.write_file` no aparece en el catálogo

#### Scenario: Comodín por servidor
- **GIVEN** `allow: ["fs.*"]` y servidores `fs` (2 tools) y `notion` (3 tools)
- **WHEN** se construye el catálogo
- **THEN** el catálogo contiene las 2 tools de `fs` y ninguna de `notion`

#### Scenario: `allow` ausente
- **GIVEN** `tool.json` sin clave `allow` y servidor `fake` con 4 tools
- **WHEN** se construye el catálogo
- **THEN** el catálogo contiene las 4 tools de `fake`

### Requirement: Servidor caído no bloquea el arranque
Un servidor que falla al conectar o al listar tools SHALL quedar registrado con estado `error` y mensaje, y el resto de servidores SHALL seguir disponibles.

#### Scenario: MCP caído no bloquea el arranque
- **GIVEN** `tool.json` con `filesystem` válido y `broken` con `command: "/no/existe"`
- **WHEN** termina el arranque del gestor
- **THEN** el estado muestra `broken` en `state: error` con mensaje, `filesystem` en `state: ready` con sus tools, y la ejecución de la tarea continúa

#### Scenario: Todos los servidores caídos
- **GIVEN** `tool.json` con un único servidor `broken` inválido
- **WHEN** termina el arranque del gestor
- **THEN** el catálogo está vacío, el estado muestra `broken` en `error` y el arranque no lanza excepción

### Requirement: Ejecución de tool con timeout
El sistema SHALL ejecutar una tool del catálogo por nombre cualificado con el timeout indicado (por defecto `limits.tool_timeout_s`, 20 s) y SHALL devolver un resultado con `ok`, `content` (texto concatenado de los bloques de texto, o el JSON de `structuredContent` si existe), `error`, `duration_ms` y `outcome_unknown`.

#### Scenario: Llamada correcta
- **GIVEN** `fake.echo` con `{text: "hola"}`
- **WHEN** se ejecuta
- **THEN** `ok = true`, `content` contiene `hola`, `error` es nulo y `duration_ms >= 0`

#### Scenario: Tool devuelve error
- **GIVEN** `fake.fail` que responde con `isError = true`
- **WHEN** se ejecuta
- **THEN** `ok = false`, `error` contiene el mensaje del servidor y `outcome_unknown = false`

#### Scenario: Timeout en tool no destructiva
- **GIVEN** `fake.slow` (sin `destructiveHint`, no en `confirm`) que tarda más que el timeout
- **WHEN** se ejecuta con timeout 1 s
- **THEN** `ok = false`, `error` indica timeout y `outcome_unknown = false`

#### Scenario: Timeout en tool destructiva
- **GIVEN** tool `fake.destroy` (`destructiveHint: true`) que tarda 25 s
- **WHEN** el proxy la ejecuta con timeout 20 s
- **THEN** `outcome_unknown = true`, no hay reintento, y el error devuelto al modelo dice que el resultado es desconocido

#### Scenario: Tool fuera del catálogo
- **GIVEN** `allow: ["fake.echo"]`
- **WHEN** se intenta ejecutar `fake.destroy`
- **THEN** la llamada es rechazada con `ok = false` y error de tool no permitida, y nunca llega al servidor

### Requirement: Estado consultable y cierre ordenado
El sistema SHALL exponer el estado de cada servidor (`name`, `state` en `ready` | `error`, `error`, `tool_count`, `allow` efectivo) y SHALL cerrar todas las sesiones al parar.

#### Scenario: Estado tras el arranque
- **GIVEN** `fake` arrancado con `allow: ["fake.echo", "fake.slow"]`
- **WHEN** se consulta el estado
- **THEN** `fake` muestra `state: ready`, `tool_count = 2` y `allow = ["fake.echo", "fake.slow"]`

#### Scenario: Parada
- **GIVEN** un gestor con un servidor stdio arrancado
- **WHEN** se para el gestor
- **THEN** el subproceso del servidor termina y una llamada posterior a cualquier tool es rechazada
