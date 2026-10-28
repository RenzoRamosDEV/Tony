# Proposal

## Why

Tony (asistente personal local con dos agentes: Jarvis `front` y Viernes `worker`) no tiene todavía código: el repositorio solo contiene la spec de producto y configuración de herramientas. Esta primera entrega construye el núcleo mínimo verificable de punta a punta — cargar un agente desde ficheros, conectar MCPs declarados en `tool/tool.json`, ejecutar al `worker` sobre Claude Agent SDK con entrada/salida estructurada y registrar cada tarea — para que `tony run viernes "<tarea>"` resuelva una tarea real con un MCP real antes de añadir orquestador, Jarvis conversacional, memoria, web o voz.

## What Changes

- Scaffold del proyecto Python 3.12 con `uv`: `pyproject.toml` (script `tony`), `uv.lock`, `.python-version`, `.gitignore`, `README.md` en español, y la estructura de carpetas `tony/core/{config,loader,mcp,runner,logging}`, `tony/apps/cli`, `agents/`, `config/`, `memory/`, `evals/`, `logs/`, `tests/`.
- Configuración `config/tony.yaml` + `config/.env` cargada con pydantic-settings en `TonySettings` (defaults completos; validación con ruta de campo; `front != worker`).
- Loader de agentes: `agents/<nombre>/agent.md` (frontmatter YAML + system prompt) y `agents/<nombre>/tool/tool.json` → `AgentSpec` / `ToolConfig`, con sustitución `${VAR}` desde entorno + `.env`, y carga tolerante a fallos por agente.
- MCP manager: conecta servidores stdio y HTTP streamable con el SDK `mcp`, lista tools, aplica `allow` (fnmatch sobre `servidor.tool`), marca `needs_confirm` (lista `confirm` o anotación `destructiveHint`), ejecuta con timeout y devuelve `ToolCallOutcome`; un servidor caído no bloquea al resto.
- Puerta de confirmación (`ConfirmGate`, puerto) con implementación CLI (`[s/N]`, 60 s); una tool no confirmada cancela la tarea.
- Runner (`AgentRunner`, puerto) con implementación `ClaudeSdkRunner`: tools integradas de Claude Code deshabilitadas, tools MCP expuestas como servidores MCP en proceso (proxies), `output_format` = JSON Schema de `TaskResult`, eventos de progreso, manejo de timeout/errores/cancelación.
- Log JSONL por tarea (`logs/<YYYYMMDD>/<task_id>.jsonl`) con `seq` creciente, `flush` por evento y redacción de secretos.
- CLI typer: `tony run <agente> "<tarea>" [--json] [--agents-dir] [--config]`, `tony version`, ayuda en español, códigos de salida 0/1/2.
- Agentes mínimos: `agents/viernes` (worker, `claude-sonnet`, MCP `filesystem` con `confirm` en escrituras) y `agents/jarvis` (front, `claude-haiku`, placeholder validable).
- Suite de pruebas sin red ni modelo real: MCP stdio falso en proceso (FastMCP como subproceso Python) y `FakeAgentRunner`.
- Primer commit en `main` con tag anotado `v1.0.0-RC.0`.

Fuera de alcance (entregas 02–05): orquestador, Jarvis conversacional, memoria, skills, subagentes, `tony mcp add`, hot reload, web, voz. Las tools nativas `delegate`, `remember`, `set_reply_mode`, `read_skill`, `run_subagent` solo se validan por nombre en `native`; no se implementan.

## Capabilities

### New Capabilities
- `core-config`: carga y validación de `config/tony.yaml` y `config/.env` (defaults, límites, alias de modelo, errores con ruta de campo, `front != worker`).
- `agent-loader`: carga de agentes desde `agents/<nombre>/` (`agent.md`, `tool/tool.json`), sustitución `${VAR}`, validación por campo y carga tolerante a agentes rotos.
- `mcp-manager`: conexión a MCPs stdio/HTTP, catálogo de tools filtrado por `allow`, marcado `needs_confirm`, ejecución con timeout y `outcome_unknown`, resiliencia ante servidores caídos y estado consultable.
- `tool-confirmation`: confirmación explícita de un solo uso para tools listadas en `confirm` o anotadas como destructivas, con expiración y cancelación de la tarea.
- `agent-runner`: ejecución de un agente `worker` con `TaskRequest` → `TaskResult`, tools integradas deshabilitadas, barrera única de ejecución vía proxies MCP, eventos de progreso y manejo de timeout/errores.
- `task-logging`: log JSONL por tarea con contrato de evento, `seq` creciente, `flush` por evento y redacción de secretos.
- `cli-run`: comando `tony run`, `tony version` y `--help` en español con códigos de salida definidos.

### Modified Capabilities
(ninguna: no existen specs principales todavía)

## Impact

- Código nuevo: paquete `tony` (`tony.core.config`, `tony.core.loader`, `tony.core.mcp`, `tony.core.runner`, `tony.core.logging`, `tony.apps.cli`), `tests/` (incl. `tests/fakes/fake_mcp_server.py`), `agents/viernes`, `agents/jarvis`.
- Dependencias nuevas (fijadas): `claude-agent-sdk==0.2.174`, `mcp` (`>=1.23,<3`, la que resuelva el SDK), `pydantic>=2`, `pydantic-settings`, `typer`, `pyyaml`, `watchfiles`, `python-dotenv`; dev: `pytest`, `pytest-asyncio`. Extras declarados pero vacíos de uso en esta entrega: `tony[web]`, `tony[voice]`.
- Sistemas externos: Claude Code CLI autenticado (el SDK usa su autenticación; no se requiere `ANTHROPIC_API_KEY`); `npx` para `@modelcontextprotocol/server-filesystem` en el cierre de la entrega.
- Sin compatibilidad hacia atrás que preservar (repositorio nuevo). Los contratos `TaskRequest`/`TaskResult`, el formato de evento JSONL y el esquema de `tool.json` quedan fijados como convenciones vinculantes para entregas posteriores.
