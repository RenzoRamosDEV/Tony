# Design

## Context

- Repositorio vacío de código: solo existe la spec de producto y configuración de herramientas. No hay compatibilidad hacia atrás que preservar; sí hay convenciones vinculantes para entregas posteriores (ver proposal.md – Impact).
- Motivación y alcance: ver proposal.md – Why / What Changes. Requisitos de comportamiento: ver `specs/*/spec.md` de este cambio.
- Restricciones verificadas del entorno:
  - Python 3.12 vía `uv`; `claude-agent-sdk==0.2.174` (depende de `mcp>=1.23,<3`); autenticación delegada al Claude Code CLI ya instalado y autenticado (no hay `ANTHROPIC_API_KEY`).
  - API pública del SDK 0.2.174 usada: `ClaudeAgentOptions(tools, allowed_tools, disallowed_tools, system_prompt, mcp_servers, permission_mode, max_turns, model, can_use_tool, setting_sources, output_format, include_partial_messages)`, `McpSdkServerConfig {type: "sdk", name, instance}`, `create_sdk_mcp_server(name, version, tools)`, decorador `tool(name, description, input_schema)`, `ClaudeSDKClient` (`query`, `receive_response`, `interrupt`), `ResultMessage {usage, total_cost_usd, structured_output, num_turns, is_error, result}`, `AssistantMessage {content: [TextBlock | ToolUseBlock | ToolResultBlock]}`, `StreamEvent {event}`, `PermissionResultAllow / PermissionResultDeny`, `ToolPermissionContext`.
- Política del proyecto: TDD obligatorio (Red → Green → Refactor), Clean Architecture / Ports & Adapters, suite sin red ni modelo real (< 60 s), primer commit en `main` con tag anotado `v1.0.0-RC.0`.

## Goals / Non-Goals

**Goals:**
- Un solo camino de ejecución de tools (el proxy MCP en proceso) que concentra `allow`, confirmación, timeout y log.
- `tony.core` independiente de CLI, web y del SDK en sus contratos: `AgentRunner`, `ConfirmGate` y `EventSink` son puertos; el SDK, la consola y el fichero JSONL son adaptadores.
- Contratos (`TaskRequest`, `TaskResult`, evento JSONL, `tool.json`, `agent.md`) estables para las entregas 02–05 (orquestador, Jarvis, memoria, web, voz).
- Toda la lógica probable con dobles en proceso.

**Non-Goals:**
- Reintentos, colas de tareas, cancelación cooperativa desde fuera del proceso, hot reload (`watchfiles` se declara como dependencia pero no se usa aquí).
- Ejecutar las tools nativas (`delegate`, `remember`, …) o exponer el servidor en proceso `tony`.
- Optimizar el arranque de MCPs (conexión secuencial es aceptable para 1–3 servidores).

## Decisions

### D1. Layout del paquete y capas

```
tony/
  core/
    config/    settings.py (TonySettings, Limits, WebSettings, VoiceSettings), env.py (carga .env)
    loader/    models.py (AgentSpec, ToolConfig, StdioServer, HttpServer), frontmatter.py, loader.py, errors.py
    mcp/       catalog.py (ToolRef, ToolCatalog), manager.py (McpManager), confirm.py (ConfirmGate port, ConfirmRequest), outcome.py (ToolCallOutcome, McpServerStatus)
    runner/    ports.py (AgentRunner, EventSink), contracts.py (TaskRequest, TaskResult), proxy.py (ToolProxyFactory), claude_sdk.py (ClaudeSdkRunner), prompt.py
    logging/   jsonl.py (JsonlEventSink), redact.py, ids.py
  apps/
    cli/       main.py (typer app), confirm_gate.py (CliConfirmGate), render.py
```

- Regla de dependencia: `tony.apps.cli` → `tony.core.*`; `tony.core.*` nunca importa `tony.apps`, `typer`, `fastapi`. Solo `tony.core.runner.claude_sdk` importa `claude_agent_sdk`; solo `tony.core.mcp.manager` importa `mcp.client.*`.
- Alternativa descartada: un módulo plano `tony/*.py`. Rechazada porque las entregas 02–05 añaden `orchestrator`, `memory`, `channels`, `voice`, `web`; el layout por subpaquete está fijado por convención del proyecto.

### D2. Puertos y adaptadores

| Puerto (`tony.core`) | Firma | Adaptador en esta entrega | Doble de prueba |
| --- | --- | --- | --- |
| `AgentRunner` | `async run(spec, request, tools, events) -> TaskResult` | `ClaudeSdkRunner` | `FakeAgentRunner` (devuelve un `TaskResult` preconfigurado y emite eventos) |
| `ConfirmGate` | `async confirm(ConfirmRequest) -> bool` | `CliConfirmGate` (stdin, `[s/N]`, 60 s) | `AutoConfirmGate(answer: bool)` |
| `EventSink` | `emit(type, payload)` (sync; el sink asigna `ts` y `seq`) | `JsonlEventSink` | `ListEventSink` (lista en memoria) |

- `ToolCatalog` es un objeto de dominio inmutable (lista de `ToolRef` + índice por `qualified`) que el runner recibe ya filtrado; el runner no conoce `allow`.
- `McpManager` es el único que habla el protocolo MCP hacia fuera y expone `call(qualified, args, timeout)`; el proxy lo usa a través de un `Callable` inyectado, por lo que el runner es probable sin manager real.
- Alternativa descartada: pasar el `McpManager` completo al runner. Rechazada: acopla el runner al transporte y dificulta el `FakeAgentRunner`.

### D3. Tony posee las conexiones MCP; el SDK ve proxies en proceso (decisión fijada)

- Tony NO entrega `mcpServers` del usuario al SDK. `McpManager` conecta cada servidor con `mcp.client.stdio.stdio_client` / `mcp.client.streamable_http.streamablehttp_client` + `ClientSession`, hace `initialize` y `list_tools` bajo `asyncio.timeout(mcp_connect_timeout_s)`.
- Por cada servidor con tools en el catálogo, `ToolProxyFactory` construye `create_sdk_mcp_server(name=<server>, version="1.0.0", tools=[...])` con un proxy por `ToolRef` (mismo `name`, `description`, `input_schema`). El SDK los nombra `mcp__<server>__<tool>`, idéntico a si el MCP se hubiera conectado directamente, así los prompts y logs no cambian si en el futuro cambia la estrategia.
- El proxy es la única barrera de ejecución, en este orden: (1) `qualified in catalog` (si no, error `tool no permitida`); (2) `needs_confirm` → `ConfirmGate.confirm(ConfirmRequest)`; `False` → resultado de error `Tool <tool> no confirmada por el usuario`, marca `cancelled` en el estado de la tarea y llama a `client.interrupt()`; (3) `manager.call(..., timeout=tool_timeout_s)`; (4) `events.emit("tool.call")` antes y `events.emit("tool.result")` después.
- `permission_mode="default"`, `tools=[]`, `disallowed_tools=[Bash, Read, Write, Edit, MultiEdit, NotebookEdit, Glob, Grep, LS, WebFetch, WebSearch, Task, TodoWrite, BashOutput, KillBash, Skill]`, `allowed_tools=["mcp__<server>__*" por servidor]`, `setting_sources=[]`, `can_use_tool` devuelve `PermissionResultDeny` para todo nombre que no empiece por `mcp__` y para todo `mcp__a__b` cuyo `a.b` no esté en el catálogo (doble defensa; el proxy ya lo rechaza).
- Razón: control total de `allow`/confirmación/timeout/log en un solo punto; el SDK no persiste ni carga nada del usuario; el modelo nunca ve tools integradas.
- Alternativa descartada: entregar `mcpServers` al SDK y filtrar con `can_use_tool` + hooks `PreToolUse`. Rechazada: la confirmación y el timeout quedarían en manos del CLI de Claude Code (procesos y permisos fuera de Tony), y el estado de servidor caído no sería observable desde Tony.

### D4. Confirmación de un solo uso (decisión fijada)

- `ConfirmRequest {confirmation_id: ulid, task_id, tool: qualified, args_normalized: json.dumps(args, sort_keys=True, ensure_ascii=False)}`. La aprobación vive solo durante la llamada al proxy; no hay caché de aprobaciones, por lo que "misma tool, otros args" o "misma tool, otra llamada" vuelve a preguntar.
- `needs_confirm = qualified in confirm or destructiveHint is True`. La anotación la aporta `mcp.types.Tool.annotations.destructiveHint`.
- Expiración: `asyncio.wait_for(gate.confirm(req), confirm_timeout_s)`; timeout ⇒ `False`. La espera de confirmación no cuenta para el timeout de 20 s de la tool, pero sí para el de 300 s de la tarea (el reloj de tarea arranca en `task.started`).
- `CliConfirmGate` lee stdin en un hilo (`asyncio.to_thread(input)`) para no bloquear el loop; respuesta válida: `{"s", "si", "sí"}` tras `strip().lower()`.
- Alternativa descartada: usar `can_use_tool` del SDK como punto de confirmación. Rechazada: no se puede ligar a `task_id`/args normalizados con expiración propia, y mezclaría la política de Tony con el modelo de permisos de Claude Code.

### D5. Timeouts y `outcome_unknown` (decisión fijada)

- Conexión MCP 10 s, tool 20 s, confirmación 60 s, tarea 300 s (configurables en `limits`).
- `McpManager.call` envuelve `session.call_tool` en `asyncio.timeout(timeout)`. Al expirar: `ok=False`, `error="timeout tras N s"`, `outcome_unknown = ref.needs_confirm` (tools `confirm` o destructivas). Nunca hay reintento; el mensaje al modelo dice explícitamente que el resultado es desconocido para que no repita la llamada.
- Timeout de tarea: `asyncio.timeout(task_timeout_s)` alrededor de todo el bucle de `receive_response`; al expirar se llama a `client.interrupt()` y se devuelve `TaskResult(status="timeout")`.

### D6. `ClaudeSdkRunner`: construcción de opciones y mapeo de mensajes

- `build_options(spec, request, catalog, settings, proxies, can_use_tool) -> ClaudeAgentOptions` es una función pura y es lo que se prueba sin lanzar el CLI.
- `system_prompt = spec.system_prompt + "\n\n## Contexto de ejecución\n- Fecha y hora: <ISO local con zona>\n- Rol: <role>\n- Restricciones:\n  - ..."`.
- `model = settings.models[spec.model]` (el alias ya se validó en el loader). `max_turns = spec.max_steps`. `output_format = {"type": "json_schema", "schema": TaskResult.model_json_schema()}`. `include_partial_messages=True` para `assistant.text` incremental.
- Prompt de usuario: `"Resuelve la siguiente tarea y devuelve exclusivamente un TaskResult JSON.\n" + request.model_dump_json()`.
- Mapeo de mensajes: `StreamEvent` con delta de texto → `assistant.text`; `AssistantMessage` con `ToolUseBlock` no genera evento (el proxy emite `tool.call`/`tool.result` con datos reales); `ResultMessage` → si `structured_output` valida como `TaskResult`, se usa; si no, `TaskResult(status="partial", resumen=result or último texto, errores=["respuesta no estructurada"])`. Si el proxy marcó `cancelled`, ese estado prevalece sobre lo que devuelva el modelo. `usage` → `task.finished.usage {input_tokens, output_tokens, total_cost_usd, num_turns}`.
- Excepciones del SDK (`CLINotFoundError`, `ProcessError`, `CLIJSONDecodeError`, cualquier `Exception`) → `TaskResult(status="error", errores=[str(exc)])`; el CLI nunca imprime trazas.
- Alternativa descartada: `query()` (función de alto nivel). Rechazada: no expone `interrupt()`, necesario para la cancelación por confirmación rechazada.

### D7. Configuración y carga

- `TonySettings(BaseSettings)` con `model_config = SettingsConfigDict(env_prefix="TONY_", extra="forbid")` y una `yaml_file` resuelta por el llamador (por defecto `config/tony.yaml`); se carga con `yaml.safe_load` y se pasa como `**data` para que pydantic devuelva `ValidationError` con `loc` (p. ej. `limits.tool_timeout_s`). El error se traduce a `ConfigError("<campo>: <motivo>")`. `front != worker` se valida con `model_validator(mode="after")`.
- `.env`: `dotenv_values("config/.env")` fusionado bajo `os.environ` (el entorno gana). El resultado (`EnvMap`) se pasa al loader para `${VAR}` y al `JsonlEventSink` para redacción.
- Loader: frontmatter con `yaml.safe_load` entre la primera y la segunda línea `---`; `AgentSpec` es `BaseModel` con `role: Literal["front","worker"]`, `max_steps: conint(ge=1, le=200)`. `ToolConfig.mcpServers: dict[str, StdioServer | HttpServer]` con un `model_validator(mode="before")` que decide el tipo por presencia de `command`/`url` y falla si hay ambos o ninguno. `allow: list[str] | None = None` (ausente ≠ `[]`). Sustitución `${VAR}` con `string.Template`-like regex `\$\{([A-Z0-9_]+)\}` y error `MissingEnvVar(var, server)`.
- `load_all` devuelve `dict[str, AgentSpec | AgentLoadError]`; `AgentLoadError` es una excepción con `agent` y `message`.

### D8. Log JSONL y redacción

- `JsonlEventSink(logs_dir, task_id, secrets: Iterable[str])` abre `logs/<YYYYMMDD>/<task_id>.jsonl` en modo `a` (crea el directorio), mantiene `seq` en memoria y hace `write` + `flush` por evento. `ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")`.
- `redact(payload, secrets)` recorre dict/list recursivamente: claves `authorization`/`api_key`/`token` (case-insensitive) → `"***"`; cualquier `str` que contenga un valor de `secrets` (valores no vacíos de `.env`) → se sustituye la ocurrencia por `***`.
- `task_id`: `uuid4().hex` (sin dependencia extra; ULID queda como opción futura compatible porque el contrato solo exige unicidad).

### D9. CLI

- `typer.Typer(help=...)` con comandos `run` y `version`; textos en español. `run` crea `TonySettings`, carga el agente (`load_agent(agents_dir / nombre)`), comprueba `role == "worker"` (si no, `typer.Exit(2)`), crea `task_id`, `JsonlEventSink`, `McpManager.start(spec.tools)`, `ClaudeSdkRunner(confirm_gate=CliConfirmGate, call=manager.call)`, ejecuta con `asyncio.run`, para el manager en `finally`, renderiza y sale con 0/1.
- Inyección para pruebas: `main.app` toma el runner de una factoría a nivel de módulo (`RunnerFactory`) que las pruebas sustituyen por `FakeAgentRunner`; el `McpManager` se sustituye por un fake que devuelve un catálogo vacío. `typer.testing.CliRunner` cubre códigos de salida, `--json` y textos.

### D10. Estrategia de pruebas (sin red ni modelo real)

- `tests/fakes/fake_mcp_server.py`: `FastMCP("fake")` con tools `echo(text)`, `fail()` (lanza error), `slow(seconds=25)` (duerme), `destroy()` con `annotations=ToolAnnotations(destructiveHint=True)`; se ejecuta como subproceso Python (`sys.executable`, `-m tests.fakes.fake_mcp_server`) vía stdio. Las pruebas de timeout usan `timeout=0.5` y `slow(seconds=2)` para mantener la suite por debajo de 60 s.
- `FakeAgentRunner`: devuelve un `TaskResult` configurado y emite la secuencia de eventos mínima; permite probar CLI, log y flujo de cancelación.
- `ClaudeSdkRunner` se cubre con `build_options` (opciones seguras) y con el mapeo `ResultMessage → TaskResult` usando objetos del SDK construidos a mano; no se lanza el CLI de Claude Code.
- Evals con modelo real solo bajo `TONY_EVALS=1` (marcador `pytest.mark.evals`, deseleccionado por defecto).

### D11. Dependencias y herramientas

- `pyproject.toml`: `[project]` `requires-python = ">=3.12,<3.13"`, deps fijadas (`claude-agent-sdk==0.2.174`, `mcp>=1.23,<3`, `pydantic>=2`, `pydantic-settings`, `typer`, `pyyaml`, `watchfiles`, `python-dotenv`); `[project.optional-dependencies] web`, `voice`; `[dependency-groups] dev = [pytest, pytest-asyncio, pytest-timeout]`; `[project.scripts] tony = "tony.apps.cli.main:app"`. `pytest-timeout` con `timeout = 30` por prueba para cumplir "la suite no cuelga".
- `agents/viernes/tool/tool.json`: `filesystem` con `npx -y @modelcontextprotocol/server-filesystem@2025.8.21 ${HOME}/notas`; si esa versión no existe en npm al implementar, se fija la última estable publicada y se anota en el README.

## Risks / Trade-offs

- [El SDK 0.2.174 podría ignorar `tools=[]` o cargar algo pese a `setting_sources=[]`] → doble defensa: `disallowed_tools` explícito + `can_use_tool` que deniega todo lo no `mcp__`; prueba de `build_options` fija estos valores.
- [`interrupt()` no detiene al instante; el modelo puede emitir texto tras la cancelación] → el estado `cancelled` fijado por el proxy prevalece sobre el `ResultMessage`; se ignoran eventos posteriores.
- [Un proxy en proceso por servidor implica un servidor MCP en memoria extra por tarea] → coste despreciable para 1–3 servidores; se reconstruye por ejecución (sin estado compartido entre tareas).
- [Timeout de 20 s puede dejar un `call_tool` colgado en el servidor real] → `asyncio.timeout` cancela la espera del cliente; el servidor stdio se cierra en `stop()`. Se acepta que un servidor HTTP pueda seguir ejecutando (por eso `outcome_unknown` en destructivas).
- [Los pares de `.env` usados como lista de redacción pueden ser cortos (p. ej. `PORT=8787`) y redactar texto legítimo] → se redactan solo valores de longitud ≥ 8; documentado en el README.
- [`npx` descarga el servidor filesystem en el primer uso y puede superar los 10 s de conexión] → el README indica ejecutar una vez `npx -y @modelcontextprotocol/server-filesystem@<ver> --help` antes del cierre; `mcp_connect_timeout_s` es configurable.
- [`structured_output` del SDK depende de que el modelo respete `output_format`] → fallback `partial` + `errores: ["respuesta no estructurada"]`; la CLI sigue devolviendo 0.
- [Conexión secuencial de MCPs alarga el arranque] → aceptable en esta entrega; `asyncio.gather` queda como mejora si se declaran más de 3 servidores.

## Migration Plan

- Repositorio nuevo: no hay migración de datos ni de API.
- Despliegue local: `uv sync` → `uv run tony --help` → `uv run pytest` → cierre manual con MCP real (`uv run tony run viernes "lista los .md de ~/notas y resume el más reciente"`).
- Rollback: `git checkout v1.0.0-RC.0` (todo el cambio llega en el primer commit etiquetado).

## Open Questions

- Versión exacta de `@modelcontextprotocol/server-filesystem` disponible en npm en el momento de implementar (se intenta `2025.8.21`; si no existe, la última estable). No afecta a specs ni tareas.
- Si `claude-agent-sdk` 0.2.174 emite `StreamEvent` de texto con `include_partial_messages=True` en todos los casos; si no, `assistant.text` se emite desde `AssistantMessage.TextBlock` (misma semántica para el log).

## Revisión post-implementación

Decisiones ajustadas tras la revisión externa de código (sin cambiar los contratos públicos):

- **D2/D3 – Catálogo sin ambigüedad.** `ToolCatalog.build` rechaza colisiones de nombre cualificado (`a` + `b.c` frente a `a.b` + `c`): conserva la primera `ToolRef`, registra la colisión en `catalog.conflicts` y `McpManager` la emite como aviso de log. El proxy y el manager resuelven siempre la misma `ToolRef` (`server`, `name`).
- **D3 – Barrera de cancelación.** El proxy comprueba `TaskState.cancelled` al entrar y de nuevo tras cada espera de confirmación, inmediatamente antes de ejecutar; en ese caso devuelve el error `Tarea cancelada; no se ejecuta <tool>` sin llamar al MCP. `interrupt()` sigue siendo best effort, no la barrera.
- **D4 – `CliConfirmGate`.** El ciclo prompt→respuesta se serializa con un `asyncio.Lock`; stdin lo lee un único hilo daemon que entrega líneas por cola (`StdinLines`), de modo que un timeout no bloquea la salida del proceso y las líneas tecleadas antes del prompt se descartan. EOF equivale a rechazo. El prompt y el aviso de timeout van a stderr para que `--json` mantenga stdout parseable.
- **D5 – `outcome_unknown` ante fallos de transporte.** Además del timeout, en tools con confirmación o destructivas un fallo de transporte tras enviar la llamada (`MCPError` con `CONNECTION_CLOSED`/`REQUEST_TIMEOUT`, `anyio.ClosedResourceError`/`BrokenResourceError`/`EndOfStream`, `ConnectionError`) se marca como resultado desconocido con el mismo mensaje de no repetir la llamada.
- **D6 – Runner.** `assistant.text` se emite por mensaje completo del asistente (no por delta), de forma que la redacción ve la cadena entera; por ello `include_partial_messages=False`. `ResultMessage.is_error` se mapea a `status="error"` con `subtype: result` como diagnóstico; `partial` queda solo para respuestas sin error no estructuradas. `strict_mcp_config=True`. El deadline de tarea arranca en `task.started` y cubre conexión, `query` y recepción; `interrupt()` y la salida del cliente tienen un presupuesto de limpieza adicional acotado (`CLEANUP_BUDGET_S = 5`), y si el cliente ya entregó el `ResultMessage` ese resultado prevalece aunque la salida exceda el presupuesto. Los esquemas de objeto sin `properties` se normalizan antes del decorador `tool` del SDK.
- **D7 – Carga tolerante.** Raíces YAML/JSON que no son mapas, YAML inválido, `models: null` y claves reservadas en el frontmatter (`system_prompt`, `path`, `tools`, `secrets`) se convierten en `ConfigError`/`AgentLoadError`; `load_all` sigue siendo tolerante.
- **D8 – Redacción con valores efectivos.** El loader registra cada valor sustituido en `${VAR}` de `tool.json` y lo expone en `AgentSpec.secrets`; el sink JSONL redacta esos valores además de los de `.env`. Contrapartida aceptada: valores no secretos sustituidos (p. ej. `${HOME}`) también se enmascaran en el log.
- **D11 – Dependencias.** `mcp>=2.3,<3`: el código usa la API 2.x (atributos snake_case, `MCPError`); mantener 1.x exigiría un adaptador explícito.
