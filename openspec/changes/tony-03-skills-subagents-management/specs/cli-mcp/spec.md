# Spec Delta

## Purpose

Define los comandos de gestión de servidores MCP de un agente desde la línea de comandos: alta, baja y listado sobre `agents/<agente>/tool/tool.json`, con validación por conexión.

## ADDED Requirements

### Requirement: Comando `tony mcp add`
El sistema SHALL ofrecer `tony mcp add <nombre> <url | -- comando args...> --agent <agente> [--allow PATRÓN ...] [--confirm TOOL ...] [--header K=V ...] [--env K=V ...] [--force]`. Un `<url>` que empiece por `http://` o `https://` SHALL producir un servidor HTTP; los tokens tras `--` SHALL ser `command` y `args` de un servidor stdio. Las opciones SHALL reconocerse aunque aparezcan después de `--`.

#### Scenario: Alta de servidor stdio
- **GIVEN** `agents/viernes/tool/tool.json` con `filesystem` y `confirm: ["filesystem.write_file"]`
- **WHEN** se ejecuta `tony mcp add fetch -- npx -y @modelcontextprotocol/server-fetch --agent viernes`
- **THEN** `mcpServers.fetch` es `{command: "npx", args: ["-y", "@modelcontextprotocol/server-fetch"]}`, `filesystem` y `confirm` se conservan

#### Scenario: Alta de servidor HTTP con cabeceras y allow
- **WHEN** se ejecuta `tony mcp add notion https://mcp.notion.com/mcp --agent viernes --header "Authorization=Bearer ${NOTION_TOKEN}" --allow notion.search`
- **THEN** `mcpServers.notion` es `{url: "https://mcp.notion.com/mcp", headers: {Authorization: "Bearer ${NOTION_TOKEN}"}}` y `allow` contiene `notion.search`

#### Scenario: Variables de entorno del servidor
- **WHEN** se ejecuta `tony mcp add x -- cmd --agent viernes --env TOKEN=${TOKEN}`
- **THEN** `mcpServers.x.env` es `{TOKEN: "${TOKEN}"}`

#### Scenario: Agente inexistente
- **WHEN** se ejecuta `tony mcp add x -- cmd --agent nadie`
- **THEN** termina con código `2` y un mensaje en español que nombra `nadie`

### Requirement: Escritura atómica que preserva el fichero
`tony mcp add` SHALL leer el `tool.json` actual, modificar solo la entrada afectada y escribirlo con indentación 2 mediante fichero temporal y sustitución; si el fichero no existe SHALL crearse. Un `<nombre>` ya existente SHALL producir un error sin modificar el fichero salvo con `--force`, que lo sustituye.

#### Scenario: Fichero inexistente
- **GIVEN** `agents/viernes/tool/` sin `tool.json`
- **WHEN** se ejecuta `tony mcp add fetch -- npx -y @modelcontextprotocol/server-fetch --agent viernes`
- **THEN** se crea `tool.json` con `mcpServers.fetch` y el resto de claves ausentes

#### Scenario: Nombre existente sin --force
- **GIVEN** `tool.json` con `mcpServers.fetch`
- **WHEN** se ejecuta `tony mcp add fetch -- otro --agent viernes`
- **THEN** termina con código `1`, el mensaje nombra `fetch` y `--force`, y el fichero no cambia

#### Scenario: Nombre existente con --force
- **GIVEN** `tool.json` con `mcpServers.fetch = {command: "a"}`
- **WHEN** se ejecuta `tony mcp add fetch -- b --agent viernes --force`
- **THEN** `mcpServers.fetch.command` es `b`

#### Scenario: Fallo al escribir
- **GIVEN** la sustitución del fichero temporal falla
- **WHEN** se ejecuta `tony mcp add`
- **THEN** el `tool.json` original queda intacto y no quedan ficheros temporales en `tool/`

### Requirement: Validación por conexión al añadir
Tras escribir, `tony mcp add` SHALL conectar al servidor con timeout de `limits.mcp_connect_timeout_s` (10 s) y mostrar `<nombre>: <N> tools (allow: todas|<patrones>)`. Si la conexión falla, la entrada SHALL quedar escrita igualmente y SHALL mostrarse una advertencia con el error; el código de salida SHALL ser `0` en ambos casos.

#### Scenario: Conexión correcta
- **GIVEN** un servidor stdio falso que expone 4 tools
- **WHEN** se ejecuta `tony mcp add fake -- python -m tests.fakes.fake_mcp_server --agent viernes`
- **THEN** la salida contiene `fake: 4 tools (allow: todas)` y el código de salida es `0`

#### Scenario: Conexión fallida
- **WHEN** se ejecuta `tony mcp add roto -- /no/existe --agent viernes`
- **THEN** `tool.json` contiene `mcpServers.roto`, la salida contiene una advertencia que nombra `roto` y el error, y el código de salida es `0`

### Requirement: Comando `tony mcp remove`
`tony mcp remove <nombre> --agent <agente>` SHALL eliminar `mcpServers.<nombre>` con la misma escritura atómica, conservando `allow`, `confirm` y `native`. Un nombre inexistente SHALL producir un error con código `1`.

#### Scenario: Baja
- **GIVEN** `tool.json` con `filesystem` y `fetch`
- **WHEN** se ejecuta `tony mcp remove fetch --agent viernes`
- **THEN** `mcpServers` solo contiene `filesystem` y las demás claves no cambian

#### Scenario: Baja de nombre inexistente
- **WHEN** se ejecuta `tony mcp remove nadie --agent viernes`
- **THEN** termina con código `1` y un mensaje que nombra `nadie`

### Requirement: Comando `tony mcp list`
`tony mcp list [--agent X] [--no-connect]` SHALL imprimir una tabla con las columnas `agente | servidor | transporte | estado | tools | allow | confirm` para cada servidor de cada agente (y subagente, como `<agente>/<subagente>`), conectando a cada servidor para obtener `estado` y `tools`; con `--no-connect` SHALL leer solo la configuración y mostrar `-` en esas columnas.

#### Scenario: Listado con conexión
- **GIVEN** `viernes` con el servidor stdio falso `fake` (`allow` ausente, `confirm: ["fake.destroy"]`)
- **WHEN** se ejecuta `tony mcp list --agent viernes`
- **THEN** la salida contiene una fila con `viernes`, `fake`, `stdio`, `ready`, `4`, `todas` y `fake.destroy`

#### Scenario: Listado sin conexión
- **WHEN** se ejecuta `tony mcp list --no-connect`
- **THEN** la salida contiene las filas de todos los agentes con `-` en `estado` y `tools`, sin arrancar ningún proceso

#### Scenario: Servidor caído
- **GIVEN** `viernes` con `roto` (`command: "/no/existe"`)
- **WHEN** se ejecuta `tony mcp list --agent viernes`
- **THEN** la fila de `roto` muestra `error` y el comando termina con código `0`

### Requirement: Ayuda en español
`tony mcp --help`, `tony mcp add --help`, `tony mcp remove --help` y `tony mcp list --help` SHALL describir cada opción en español, y `tony --help` SHALL listar `mcp`.

#### Scenario: Ayuda de add
- **WHEN** se ejecuta `tony mcp add --help`
- **THEN** la salida describe `--agent`, `--allow`, `--confirm`, `--header`, `--env` y `--force` en español
