# Tasks

Convenciones de este listado: TDD obligatorio (Red → Green → Refactor) por módulo; cada grupo empieza con las pruebas en rojo y termina con `uv run pytest <fichero>` en verde. Ninguna prueba usa red ni modelo real. Identificadores en inglés, textos de usuario en español. Ver design.md para la estructura de módulos (D1) y la estrategia de pruebas (D10).

## 1. Scaffold del proyecto

- [x] 1.1 Crear `pyproject.toml` (nombre `tony`, `requires-python = ">=3.12,<3.13"`, script `tony = "tony.apps.cli.main:app"`, deps fijadas y extras `web`/`voice`, grupo `dev` con `pytest`, `pytest-asyncio`, `pytest-timeout`), `.python-version` = `3.12` y ampliar el `.gitignore` existente (conservar sus entradas actuales y añadir `.venv/`, `config/.env`, `logs/`, `memory/*.sqlite*`, `node_modules/`, `tony/apps/web/frontend/dist/`); verificar con `uv sync` que genera `uv.lock` sin errores
- [x] 1.2 Crear la estructura de paquetes `tony/__init__.py` (con `__version__`), `tony/core/{config,loader,mcp,runner,logging}/__init__.py`, `tony/apps/cli/__init__.py`, directorios `agents/jarvis`, `agents/viernes/tool`, `config/`, `memory/.gitkeep`, `evals/.gitkeep`, `logs/.gitkeep`, `tests/__init__.py`, `tests/fakes/__init__.py`; verificar con `uv run python -c "import tony.core.config, tony.core.loader, tony.core.mcp, tony.core.runner, tony.core.logging, tony.apps.cli"`
- [x] 1.3 Crear `tests/conftest.py` (fixture `tmp_repo` con `config/`, `agents/`, `logs/` temporales; `asyncio_mode = "auto"` y `timeout = 30` en `[tool.pytest.ini_options]`; marcador `evals` deseleccionado salvo `TONY_EVALS=1`); verificar con `uv run pytest --collect-only` que no hay errores de configuración
- [x] 1.4 Crear `config/tony.yaml` de ejemplo con los valores por defecto comentados y `config/.env.example`; verificar que `config/.env` está ignorado con `git check-ignore config/.env`

## 2. Config (`tony.core.config`)

- [x] 2.1 RED: escribir `tests/core/test_config.py` con casos de `specs/core-config`: defaults sin fichero, fichero parcial (`web.port=9000`), alias de modelo adicional, tipo inválido en `limits.tool_timeout_s` (el error incluye la ruta), `reply_mode` fuera de dominio, `front == worker`, `.env` disponible para `${VAR}`, prioridad del entorno sobre `.env`; verificar que falla con `ImportError`/`AssertionError` (`uv run pytest tests/core/test_config.py`)
- [x] 2.2 GREEN: implementar `tony/core/config/settings.py` (`TonySettings`, `Limits`, `WebSettings`, `VoiceSettings`, `ConfigError` con ruta de campo, validador `front != worker`, `load_settings(path | None)`) y `tony/core/config/env.py` (`load_env(path) -> EnvMap` fusionando `dotenv_values` bajo `os.environ`); verificar `uv run pytest tests/core/test_config.py` en verde
- [x] 2.3 REFACTOR: revisar nombres y eliminar duplicación; verificar que la suite sigue en verde y que `tony.core.config` no importa `typer` ni `claude_agent_sdk` (`uv run python -c "import tony.core.config, sys; assert 'typer' not in sys.modules"`)

## 3. Loader (`tony.core.loader`)

- [x] 3.1 RED: escribir `tests/core/test_loader_agent.py` con casos de `specs/agent-loader` para `agent.md`: agente completo (ejemplo de Jarvis), opcionales ausentes, `max_steps` fuera de rango, rol inválido, frontmatter ausente, alias de modelo desconocido; verificar que falla
- [x] 3.2 RED: escribir `tests/core/test_loader_tools.py` con casos para `tool.json`: ejemplo de referencia stdio+HTTP, servidor con `command` y `url`, servidor sin ninguno, `native` fuera de catálogo, `tool.json` ausente → config vacía, `allow` ausente ≠ `[]`, sustitución `${VAR}` en `args`/`headers`, variable ausente nombra variable y servidor; verificar que falla
- [x] 3.3 RED: escribir `tests/core/test_loader_all.py`: un agente roto entre varios, directorio vacío; verificar que falla
- [x] 3.4 GREEN: implementar `tony/core/loader/models.py` (`AgentSpec`, `Persona`, `Style`, `ToolConfig`, `StdioServer`, `HttpServer`, `NATIVE_TOOLS`), `frontmatter.py` (`split_frontmatter`), `loader.py` (`load_agent(path, settings, env)`, `load_all(agents_dir, settings, env)`, `substitute_env`) y `errors.py` (`AgentLoadError`, `MissingEnvVar`); verificar `uv run pytest tests/core/test_loader_*.py` en verde
- [x] 3.5 REFACTOR: separar la sustitución `${VAR}` en función pura reutilizable y simplificar validadores; verificar suite en verde

## 4. MCP falso de pruebas (`tests/fakes`)

- [x] 4.1 Crear `tests/fakes/fake_mcp_server.py` con `FastMCP("fake")` y tools `echo(text)`, `fail()` (devuelve error), `slow(seconds: float)` (duerme), `destroy()` con `annotations.destructiveHint = true`, ejecutable como `python -m tests.fakes.fake_mcp_server` por stdio; verificar manualmente con `uv run python -c` que `mcp.client.stdio` lista 4 tools y `destroy` lleva la anotación (`tests/fakes/test_fake_mcp_server.py`)
- [x] 4.2 Crear `tests/fakes/fake_runner.py` (`FakeAgentRunner(result, events=[...])`), `tests/fakes/sinks.py` (`ListEventSink`) y `tests/fakes/gates.py` (`AutoConfirmGate(answer)`); verificar con una prueba trivial que implementan los puertos (`tests/fakes/test_doubles.py`)

## 5. MCP manager (`tony.core.mcp`)

- [x] 5.1 RED: escribir `tests/core/test_mcp_catalog.py` (unitario, sin subproceso) con casos de `specs/mcp-manager`: `destructiveHint` → `needs_confirm`, `confirm` → `needs_confirm`, `input_schema` preservado, `allow` exacto, comodín `fs.*`, `allow` ausente; verificar que falla
- [x] 5.2 RED: escribir `tests/core/test_mcp_manager.py` (integración con el MCP falso por stdio): arranque y listado (`tool_count = 4`), filtro de servidores, servidor `broken` con `command: /no/existe` no bloquea, todos caídos → catálogo vacío sin excepción, `echo` ok, `fail` → `ok=False`, timeout en `slow` no destructiva → `outcome_unknown=False`, timeout en `destroy` → `outcome_unknown=True` sin reintento, tool fuera del catálogo rechazada sin llegar al servidor, `status()` con `allow` efectivo, `stop()` termina el subproceso; usar timeouts de 0,5 s y `slow(seconds=2)`; verificar que falla
- [x] 5.3 GREEN: implementar `tony/core/mcp/catalog.py` (`ToolRef`, `ToolCatalog.build(tools_by_server, allow, confirm)`), `outcome.py` (`ToolCallOutcome`, `McpServerStatus`), `manager.py` (`McpManager.start(tool_config, server_filter=None)`, `call(qualified, args, timeout)`, `status()`, `stop()` con `AsyncExitStack` por servidor y `asyncio.timeout`); verificar `uv run pytest tests/core/test_mcp_*.py` en verde y en < 20 s
- [x] 5.4 REFACTOR: extraer la conversión de `CallToolResult` a texto/JSON en función pura con su prueba; verificar suite en verde

## 6. Puerta de confirmación (`tony.core.mcp.confirm` + `tony.apps.cli.confirm_gate`)

- [x] 6.1 RED: escribir `tests/core/test_confirm.py` con casos de `specs/tool-confirmation`: `ConfirmRequest` normaliza args con claves ordenadas, `confirmation_id` único por solicitud, la misma tool con otros args genera otra solicitud, texto `sí, confirmo` devuelto por una tool no aprueba nada; y `tests/apps/test_cli_confirm_gate.py`: `Sí`/`si`/`s` → `True`, `n`/vacío → `False`, timeout → `False`, prompt exacto `Viernes quiere ejecutar <tool> con <args JSON>. ¿Confirmas? [s/N]` (inyectando la función de lectura y el nombre del agente); verificar que falla
- [x] 6.2 GREEN: implementar `tony/core/mcp/confirm.py` (`ConfirmRequest`, `ConfirmGate` Protocol, `normalize_args`) y `tony/apps/cli/confirm_gate.py` (`CliConfirmGate(agent_name, timeout_s, reader=input)` con `asyncio.to_thread` y `asyncio.wait_for`); verificar `uv run pytest tests/core/test_confirm.py tests/apps/test_cli_confirm_gate.py` en verde
- [x] 6.3 REFACTOR: asegurar que `tony.core.mcp.confirm` no importa nada de `tony.apps`; verificar con prueba de importación en `tests/test_architecture.py` (que `tony.core` no importe `tony.apps`, `typer`, `fastapi`)

## 7. Log JSONL (`tony.core.logging`)

- [x] 7.1 RED: escribir `tests/core/test_logging.py` con casos de `specs/task-logging`: línea equivalente al ejemplo de `tool.call` (`schema_version`, `ts` con `Z`, `seq`), `seq` 1..4, ruta `logs/<YYYYMMDD>/<task_id>.jsonl`, durabilidad (líneas completas tras dos eventos sin cerrar), redacción `Authorization`, valor de `.env` dentro de un string, clave anidada `API_KEY`; y `tests/core/test_redact.py` unitario de `redact`; verificar que falla
- [x] 7.2 GREEN: implementar `tony/core/logging/ids.py` (`new_task_id`), `redact.py` (`redact(payload, secrets)`, claves sensibles case-insensitive, valores de `.env` de longitud ≥ 8) y `jsonl.py` (`JsonlEventSink(logs_dir, task_id, secrets)` con `emit`, `path`, `close`, append + `flush` por evento); verificar `uv run pytest tests/core/test_logging.py tests/core/test_redact.py` en verde
- [x] 7.3 REFACTOR: unificar la generación de `ts` en un helper y documentar el contrato de evento en el docstring del módulo; verificar suite en verde

## 8. Runner (`tony.core.runner`)

- [x] 8.1 RED: escribir `tests/core/test_contracts.py`: `TaskRequest`/`TaskResult` validan y rechazan `status` fuera de dominio; `TaskResult.model_json_schema()` es serializable; verificar que falla
- [x] 8.2 RED: escribir `tests/core/test_runner_options.py` con casos de `specs/agent-runner`: `build_options` produce `tools=[]`, `disallowed_tools` con la lista integrada, `allowed_tools=["mcp__fs__*"]`, `permission_mode="default"`, `setting_sources=[]`, `max_turns=max_steps`, `model` resuelto, `output_format` con el esquema de `TaskResult`, `include_partial_messages=True`, system prompt con bloque de contexto (fecha con zona, rol, restricciones); `can_use_tool` deniega `Bash` y `mcp__fs__write_file` fuera de catálogo y permite `mcp__fs__read_file`; verificar que falla
- [x] 8.3 RED: escribir `tests/core/test_runner_proxy.py`: el proxy de `fake.echo` emite `tool.call` y `tool.result` y devuelve el contenido; tool no confirmada (`AutoConfirmGate(False)`) devuelve `Tool fake.destroy no confirmada por el usuario`, marca `cancelled` y llama a `interrupt` (espía); tool con `needs_confirm=False` no consulta la puerta; servidor en proceso creado con `create_sdk_mcp_server` expone el nombre/descripción/esquema originales; verificar que falla
- [x] 8.4 RED: escribir `tests/core/test_runner_result.py`: `ResultMessage` con `structured_output` válido → `TaskResult` idéntico; sin salida estructurada → `partial` + `respuesta no estructurada`; estado `cancelled` prevalece; excepción del motor → `error` con mensaje y sin traza; timeout de tarea (`task_timeout_s=0.2` con cliente falso que nunca responde) → `timeout`; `task.finished.usage` con tokens/coste/turnos; verificar que falla
- [x] 8.5 GREEN: implementar `tony/core/runner/contracts.py` (`TaskRequest`, `TaskResult`), `ports.py` (`AgentRunner`, `EventSink` Protocols), `prompt.py` (`build_system_prompt`, `build_user_prompt`), `proxy.py` (`ToolProxyFactory(catalog, call, gate, events, task_state)` → lista de `McpSdkServerConfig`), `claude_sdk.py` (`build_options`, `make_can_use_tool`, `ClaudeSdkRunner` con `ClaudeSDKClient`, `asyncio.timeout(task_timeout_s)`, mapeo de `StreamEvent`/`AssistantMessage`/`ResultMessage`, captura de excepciones, factoría de cliente inyectable); verificar `uv run pytest tests/core/test_runner_*.py tests/core/test_contracts.py` en verde
- [x] 8.6 REFACTOR: aislar `ResultMessage → TaskResult` y el mapeo de eventos en funciones puras; verificar suite en verde y que solo `claude_sdk.py` y `proxy.py` importan `claude_agent_sdk`

## 9. CLI (`tony.apps.cli`)

- [x] 9.1 RED: escribir `tests/apps/test_cli_run.py` con `typer.testing.CliRunner` y `FakeAgentRunner` (vía factoría inyectable y `McpManager` falso) con casos de `specs/cli-run`: `status ok` → código 0 y salida con `resumen`, pasos `1. a`/`2. b`, línea `tokens: in/out · coste: $X · log: <ruta>`; errores impresos; `--json` → JSON parseable y nada más en stdout; `partial` → 0; `cancelled` → 1; agente inexistente → 2 con mensaje que nombra al agente; `jarvis` (front) → 2; agente roto → 2 con el error de carga; `--agents-dir` y `--config` respetados; `tony run --help` describe las tres opciones en español; `tony version` imprime `__version__`; verificar que falla
- [x] 9.2 GREEN: implementar `tony/apps/cli/main.py` (`app`, comandos `run` y `version`, ayuda en español, `RunnerFactory`/`ManagerFactory` inyectables, `asyncio.run`, `finally: manager.stop()`, códigos 0/1/2) y `tony/apps/cli/render.py` (`render_text(result, usage, log_path)`, `render_json(result)`); verificar `uv run pytest tests/apps/test_cli_run.py` en verde y `uv run tony --help` muestra ayuda en español
- [x] 9.3 REFACTOR: mover la orquestación de `run` (config → agente → MCPs → runner → log) a una función `run_task(...)` en `tony/apps/cli/run_task.py` probable sin typer; verificar suite en verde

## 10. Agentes mínimos y README

- [x] 10.1 Crear `agents/viernes/agent.md` (`role: worker`, `model: claude-sonnet`, prompt en español que exige planificar, usar tools y devolver `TaskResult`) y `agents/viernes/tool/tool.json` (`filesystem`: `npx -y @modelcontextprotocol/server-filesystem@2025.8.21 ${HOME}/notas` — o la última estable si esa versión no existe en npm —, `confirm: ["filesystem.write_file", "filesystem.edit_file", "filesystem.move_file"]`); verificar con `tests/agents/test_bundled_agents.py` que `load_agent` lo carga y que `needs_confirm` queda marcado para las tres tools (catálogo construido con nombres simulados)
- [x] 10.2 Crear `agents/jarvis/agent.md` (`role: front`, `model: claude-haiku`, ejemplo de persona/estilo) y `agents/jarvis/tool/tool.json` (`native: ["delegate","remember","set_reply_mode"]`, sin `mcpServers`); verificar en `tests/agents/test_bundled_agents.py` que `load_all(agents/)` devuelve `jarvis` y `viernes` sin errores
- [x] 10.3 Escribir `README.md` en español: instalación (`uv sync`, `uv run tony --help`), autenticación vía Claude Code CLI, creación de `~/notas` si no existe, precarga de `npx -y @modelcontextprotocol/server-filesystem@<ver> --help`, formato de `agent.md`/`tool.json`, dónde quedan los logs, nota sobre redacción de secretos; verificar que cada comando documentado se ejecuta tal cual

## 11. Verificación de la entrega

- [x] 11.1 Ejecutar `uv run pytest` completa y verificar que termina en < 60 s, sin acceso a red ni al modelo (`TONY_EVALS` sin definir)
- [x] 11.2 Ejecutar mutation testing (p. ej. `uv run mutmut run --paths-to-mutate tony/core`) limitado a los módulos de esta entrega con tope de 3 minutos; verificar puntuación > 95 % o justificar los mutantes supervivientes en el mensaje de cierre
- [x] 11.3 Verificar `uv run tony --help`, `uv run tony run --help` y `uv run tony version` en terminal
- [x] 11.4 Cierre con MCP real: con Claude Code autenticado y `~/notas` con al menos un `.md`, ejecutar `uv run tony run viernes "lista los .md de ~/notas y resume el más reciente"` y verificar `status: ok` y que el JSONL en `logs/<fecha>/<task_id>.jsonl` contiene eventos `tool.call` para `filesystem.list_directory` y `filesystem.read_file`
- [x] 11.5 Git: en `main`, `git add` de todo salvo ignorados, primer commit con mensaje `feat(core): scaffold tony with loader, mcp manager and run command` (sin ningún trailer `Co-Authored-By`), y tag anotado `git tag -a v1.0.0-RC.0 -m "chore: Initial release candidate"`; verificar con `git log --oneline -1` y `git tag -n1 v1.0.0-RC.0`

## Workflow follow-up

- Archivar el cambio con `openspec archive` una vez revisado y verificado el cierre de la entrega.
