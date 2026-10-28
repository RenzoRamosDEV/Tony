# Spec Delta

## Purpose

Define el inventario de agentes desde la línea de comandos: el listado de agentes y subagentes con su estado de carga y la impresión del `AgentSpec` resuelto sin secretos.

## ADDED Requirements

### Requirement: Comando `tony agents`
`tony agents [--agents-dir PATH] [--config PATH]` SHALL listar cada agente del directorio y, indentados bajo él, sus subagentes, con las columnas `nombre | rol | modelo | skills | MCP | nativas` (número de skills, número de servidores MCP y lista de tools nativas). Un agente o subagente que no carga SHALL mostrarse con `✗` y el error, sin impedir el listado de los demás. El código de salida SHALL ser `0`.

#### Scenario: Listado con subagente
- **GIVEN** `viernes` (`worker`, `claude-sonnet`, 1 skill, 1 MCP, `native: ["read_skill", "run_subagent"]`) con el subagente `investigador` (`worker`, `claude-sonnet`, 0 skills, 0 MCP propios) y `jarvis` (`front`, `claude-haiku`)
- **WHEN** se ejecuta `tony agents`
- **THEN** la salida contiene una fila `viernes`, `worker`, `claude-sonnet`, `1`, `1`, `read_skill, run_subagent`; una fila indentada `investigador`; y una fila `jarvis`, `front`, `claude-haiku`

#### Scenario: Agente roto
- **GIVEN** `agents/roto/agent.md` con `role: helper`
- **WHEN** se ejecuta `tony agents`
- **THEN** la fila de `roto` empieza por `✗` e incluye `role`, las demás filas se muestran y el código de salida es `0`

#### Scenario: Skill inválida
- **GIVEN** `viernes` con una skill sin `description`
- **WHEN** se ejecuta `tony agents`
- **THEN** la fila de `viernes` se muestra y debajo aparece una línea `✗ skill <nombre>: <error>`

### Requirement: Comando `tony agents show`
`tony agents show <nombre>` SHALL imprimir en YAML el `AgentSpec` resuelto (frontmatter, `tools` con los servidores ya sustituidos, skills con nombre, descripción y triggers, y subagentes), con todo valor procedente de `config/.env` o de cabeceras `Authorization` sustituido por `***`. `<nombre>` SHALL aceptar `<agente>/<subagente>`. Un agente inexistente SHALL terminar con código `2`.

#### Scenario: Spec resuelto sin secretos
- **GIVEN** `.env` con `NOTION_TOKEN=s3cr3t` y `viernes` con `headers: {Authorization: "Bearer ${NOTION_TOKEN}"}`
- **WHEN** se ejecuta `tony agents show viernes`
- **THEN** la salida es YAML con `name: viernes`, `role: worker`, los servidores de `tools.mcpServers` y `Authorization: '***'`, y no contiene `s3cr3t`

#### Scenario: Subagente
- **WHEN** se ejecuta `tony agents show viernes/investigador`
- **THEN** la salida es el YAML del subagente con `name: investigador`

#### Scenario: Agente inexistente
- **WHEN** se ejecuta `tony agents show nadie`
- **THEN** termina con código `2` y un mensaje en español que nombra `nadie`

### Requirement: Ayuda en español
`tony agents --help` y `tony agents show --help` SHALL describir el comando y sus opciones en español, y `tony --help` SHALL listar `agents`.

#### Scenario: Ayuda
- **WHEN** se ejecuta `tony agents --help`
- **THEN** la salida describe `show`, `--agents-dir` y `--config` en español
