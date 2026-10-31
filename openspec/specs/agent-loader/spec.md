# agent-loader Specification

## Purpose
Define cómo Tony carga la definición de un agente desde su carpeta (`agents/<nombre>/agent.md` y `agents/<nombre>/tool/tool.json`), qué campos acepta, cómo resuelve `${VAR}` y cómo se comporta ante agentes mal formados.

## Requirements

### Requirement: Definición de agente en `agent.md`
El sistema SHALL cargar `agents/<nombre>/agent.md` como un frontmatter YAML delimitado por `---` seguido de un cuerpo markdown que es el system prompt. El frontmatter SHALL aceptar: `name` (str, obligatorio), `role` (`front` | `worker`, obligatorio), `model` (alias, obligatorio), `engine` (str, opcional, por defecto `claude_sdk`), `persona {address: "" , language: "es"}`, `style {voice: "", text: ""}`, `max_steps` (entero 1..200, por defecto 20) y `wait_phrase` (por defecto `"Dame un momento."`).

#### Scenario: Agente completo
- **GIVEN** `agents/jarvis/agent.md` con frontmatter `name: jarvis`, `role: front`, `model: claude-haiku`, `persona: {address: señor, language: es}`, `style: {voice: "Frases cortas, sin markdown, números redondeados.", text: "Markdown, detalle completo, tablas si ayudan."}`, `max_steps: 20` y cuerpo `Eres Jarvis, el asistente personal de Renzo...`
- **WHEN** se carga el agente
- **THEN** la definición resultante tiene esos valores, `system_prompt` igual al cuerpo sin el frontmatter y `path` apuntando a la carpeta del agente

#### Scenario: Campos opcionales ausentes
- **GIVEN** un `agent.md` cuyo frontmatter solo define `name`, `role` y `model`
- **WHEN** se carga el agente
- **THEN** `persona.language` es `es`, `persona.address` es vacío, `max_steps` es `20`, `wait_phrase` es `Dame un momento.` y `engine` es `claude_sdk`

#### Scenario: `max_steps` fuera de rango
- **GIVEN** un `agent.md` con `max_steps: 500`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que nombra `max_steps` y el rango permitido `1..200`

#### Scenario: Rol inválido
- **GIVEN** un `agent.md` con `role: helper`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que nombra `role` y los valores permitidos `front` y `worker`

#### Scenario: Frontmatter ausente
- **GIVEN** un `agent.md` sin delimitadores `---`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que indica que falta el frontmatter

#### Scenario: `engine` declarado y válido
- **GIVEN** un `agent.md` con `engine: openai_gpt` y `tony.yaml` con ese perfil declarado en `engines`
- **WHEN** se carga el agente
- **THEN** la definición resultante tiene `engine: openai_gpt`

#### Scenario: `engine` desconocido
- **GIVEN** un `agent.md` con `engine: no_declarado` y `tony.yaml` sin ese perfil en `engines`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que nombra `no_declarado` y los perfiles disponibles

### Requirement: Alias de modelo conocido
El alias `model` del agente SHALL existir en la tabla `models` de la configuración global; en caso contrario la carga del agente SHALL fallar nombrando el alias desconocido y los alias disponibles.

#### Scenario: Alias desconocido
- **GIVEN** un `agent.md` con `model: claude-ultra` y `models` con solo `claude-haiku` y `claude-sonnet`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que incluye `claude-ultra`

### Requirement: Configuración de tools en `tool/tool.json`
El sistema SHALL cargar `agents/<nombre>/tool/tool.json` con `mcpServers` (mapa nombre → servidor stdio `{command, args=[], env={}}` o HTTP `{url, headers={}}`), `native` (lista de nombres del catálogo `delegate`, `remember`, `set_reply_mode`, `read_skill`, `run_subagent`), `allow` (lista o ausente) y `confirm` (lista, por defecto vacía). Un servidor SHALL ser stdio si tiene `command` y HTTP si tiene `url`; tener ambos o ninguno SHALL ser un error.

#### Scenario: Ejemplo de referencia con stdio y HTTP
- **GIVEN** un `tool.json` con `mcpServers: {filesystem: {command: npx, args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/renzo"]}, notion: {url: "https://mcp.notion.com/mcp"}}`, `native: ["run_subagent", "read_skill", "remember"]`, `allow: ["filesystem.*", "notion.search"]`, `confirm: ["filesystem.write_file", "filesystem.delete"]`
- **WHEN** se carga la configuración de tools
- **THEN** `filesystem` es un servidor stdio, `notion` es un servidor HTTP, y `native`, `allow` y `confirm` conservan sus listas

#### Scenario: Servidor con `command` y `url`
- **GIVEN** un `tool.json` donde `mcpServers.x` tiene `command` y `url`
- **WHEN** se carga la configuración de tools
- **THEN** la carga falla con un error que nombra el servidor `x`

#### Scenario: Servidor sin `command` ni `url`
- **GIVEN** un `tool.json` donde `mcpServers.x` es `{args: []}`
- **WHEN** se carga la configuración de tools
- **THEN** la carga falla con un error que nombra el servidor `x`

#### Scenario: Tool nativa fuera del catálogo
- **GIVEN** un `tool.json` con `native: ["teleport"]`
- **WHEN** se carga la configuración de tools
- **THEN** la carga falla con un error que incluye `teleport` y el catálogo permitido

#### Scenario: `tool.json` ausente
- **GIVEN** un agente sin carpeta `tool/` o sin `tool/tool.json`
- **WHEN** se carga el agente
- **THEN** la configuración de tools es vacía (`mcpServers = {}`, `native = []`, `allow` ausente, `confirm = []`) y la carga no falla

#### Scenario: `allow` ausente frente a lista vacía
- **GIVEN** un `tool.json` sin clave `allow`
- **WHEN** se carga la configuración de tools
- **THEN** `allow` se conserva como ausente (no como lista vacía), lo que significa "todas las tools"

### Requirement: Sustitución de variables `${VAR}`
El sistema SHALL sustituir toda ocurrencia `${VAR}` en `args`, `env`, `url` y `headers` de cada servidor usando el entorno del proceso y los pares de `config/.env`. Si una variable no está definida, la carga SHALL fallar con un error que nombra la variable y el servidor.

#### Scenario: Sustitución en args
- **GIVEN** `HOME=/home/renzo` y un servidor con `args: ["${HOME}/notas"]`
- **WHEN** se carga la configuración de tools
- **THEN** `args` es `["/home/renzo/notas"]`

#### Scenario: Sustitución en cabeceras HTTP
- **GIVEN** `NOTION_TOKEN=abc` en `.env` y un servidor con `headers: {Authorization: "Bearer ${NOTION_TOKEN}"}`
- **WHEN** se carga la configuración de tools
- **THEN** `headers.Authorization` es `Bearer abc`

#### Scenario: Variable ausente
- **GIVEN** un servidor `notion` con `url: "${NOTION_URL}"` y `NOTION_URL` sin definir
- **WHEN** se carga la configuración de tools
- **THEN** la carga falla con un error que incluye `NOTION_URL` y `notion`

### Requirement: Carga tolerante de todos los agentes
El sistema SHALL poder cargar todos los agentes de un directorio devolviendo, por nombre de carpeta, la definición cargada o el error de carga; un agente roto SHALL NOT impedir cargar los demás.

#### Scenario: Un agente roto entre varios
- **GIVEN** `agents/viernes` válido y `agents/roto` con `role: helper`
- **WHEN** se cargan todos los agentes
- **THEN** el resultado contiene `viernes` con su definición y `roto` con un error que nombra `role`

#### Scenario: Directorio vacío
- **GIVEN** un directorio de agentes sin subcarpetas
- **WHEN** se cargan todos los agentes
- **THEN** el resultado es un mapa vacío y no hay error

### Requirement: Skills dentro de la carpeta del agente
Al cargar un agente, el sistema SHALL cargar cada `skills/<nombre>/SKILL.md` de su carpeta y exponer la lista de skills válidas y la lista de errores de las inválidas en la definición del agente. Una skill inválida SHALL NOT hacer fallar la carga del agente.

#### Scenario: Agente con skills
- **GIVEN** `agents/viernes/skills/resumen-web/SKILL.md` válida y `agents/viernes/skills/mala/SKILL.md` sin `description`
- **WHEN** se carga `viernes`
- **THEN** la definición tiene la skill `resumen-web`, un error de skill que nombra `mala`, y la carga no falla

### Requirement: Subagentes dentro de la carpeta del agente
Al cargar un agente, el sistema SHALL cargar cada `subagents/<nombre>/` como un agente (con su `agent.md`, `skills/` y `tool/tool.json`) y exponerlos por nombre en la definición del padre, junto con el error de cada subagente que no cargue. Un subagente roto SHALL NOT hacer fallar la carga del padre. Cada subagente SHALL conocer el nombre de su padre.

#### Scenario: Subagente válido
- **GIVEN** `agents/viernes/subagents/investigador/agent.md` con `name: investigador`, `role: worker`, `model: claude-sonnet` y sin `tool/tool.json`
- **WHEN** se carga `viernes`
- **THEN** `viernes` tiene el subagente `investigador` con configuración de tools vacía y padre `viernes`

#### Scenario: Subagente roto
- **GIVEN** `agents/viernes/subagents/roto/agent.md` con `role: helper`
- **WHEN** se carga `viernes`
- **THEN** `viernes` carga, no tiene el subagente `roto` y registra un error de subagente que nombra `roto` y `role`

#### Scenario: Subagente con rol front
- **GIVEN** `subagents/x/agent.md` con `role: front`
- **WHEN** se carga el padre
- **THEN** el subagente carga y se registra una advertencia que nombra `x` y los roles `front`/`worker`

### Requirement: Profundidad de carga de subagentes
Un subagente SHALL NOT cargar su propia carpeta `subagents/` y, si su `tool.json` declara `run_subagent` en `native`, el nombre SHALL eliminarse de la lista con una advertencia.

#### Scenario: Nivel 2 ignorado
- **GIVEN** `subagents/investigador/subagents/otro/agent.md` válido
- **WHEN** se carga el padre
- **THEN** `investigador` no tiene subagentes

#### Scenario: run_subagent eliminado del subagente
- **GIVEN** `subagents/investigador/tool/tool.json` con `native: ["run_subagent", "read_skill"]`
- **WHEN** se carga el padre
- **THEN** `native` del subagente es `["read_skill"]` y se registra una advertencia

### Requirement: Inventario tolerante con subagentes
La carga de todos los agentes de un directorio SHALL incluir, para cada agente cargado, sus subagentes y sus errores de subagentes y de skills, de modo que un inventario pueda mostrarlos sin volver a leer el disco.

#### Scenario: Inventario completo
- **GIVEN** `viernes` con el subagente `investigador` y `jarvis` sin subagentes
- **WHEN** se cargan todos los agentes
- **THEN** el resultado contiene `viernes` con `investigador` entre sus subagentes y `jarvis` con un mapa de subagentes vacío
