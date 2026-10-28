# Design

## Context

- Estado actual (entregas 01 y 02 en `main`): puertos estables que esta entrega reutiliza sin cambiar su firma: `AgentRunner.run(spec, request, tools, events)`, `EventSink.emit`, `ConfirmGate.confirm(ConfirmRequest) -> bool`, `ConversationRunner.open(spec, catalog, handlers, events)`, `McpManager.start/call/status/stop`, `ToolCatalog.build(tools_by_server, allow, confirm)`, `Orchestrator.submit(request, parent_id=None)` (las subtareas ya corren en paralelo sin ocupar el hueco raíz), `ConfirmationRegistry` con cerrojo por owner, `TaskEventBus`/`TaskEventSink`, `JsonlEventSink`, `CancelToken`, `Clock`/`FakeClock`.
- `NativeToolSet` acepta `read_skill`/`run_subagent` y los ignora con advertencia; `AgentSpec.tools.native` ya los valida contra `NATIVE_TOOLS`. `ClaudeSdkRunner` no construye ningún servidor nativo para el `worker`. `SdkWorkerFactory` mantiene un `McpManager` por proceso con arranque perezoso.
- `watchfiles` está declarado en `pyproject.toml` y sin uso. `pytest` tiene `testpaths = ["tests"]` y el marcador `evals` registrado; `tests/conftest.py` salta `evals` sin `TONY_EVALS=1`, regla que no alcanza a `evals/` (fuera de `tests/`).
- Reglas de arquitectura vigentes (`tests/test_architecture.py`): `tony.core` no importa `tony.apps`, `typer` ni `fastapi`; `claude_agent_sdk` solo en `runner.{claude_sdk,proxy,conversation,native_tools}`; `mcp.client` solo en `mcp.manager`; `sqlite3` solo en `memory.conversations`; `runner`/`orchestrator`/`memory` no importan `channels`.
- Motivación y alcance: ver proposal.md. Comportamiento exigido: ver `specs/*/spec.md` de este cambio.

## Goals / Non-Goals

**Goals:**
- Skills y subagentes como datos en la carpeta del agente; ningún nombre de skill, subagente o MCP en Python.
- Un único camino de ejecución para tareas y subtareas (orquestador + `SdkWorkerFactory`), con el proxy como única barrera también para los hijos.
- Hot reload como servicio del core (`ConfigWatcher` + `AgentReloader` + generaciones), consumido por la CLI; el canal web lo reutiliza sin tocarlo.
- Comandos de gestión y diagnóstico como adaptadores finos sobre funciones puras del core, probables sin red.
- Evals deterministas por defecto (fixtures) y reproducibles con modelo real bajo `TONY_EVALS=1`.

**Non-Goals:**
- Subagentes en `tony run` (devuelven error explicativo; ver D6), reintentos, prioridades o profundidad > 1.
- Hot reload del `front`, de `agent.md`, de skills o de `tony.yaml`; recarga por cambios en `.env`.
- Reenvío del progreso de los hijos al canal línea a línea (solo `subtask.started/finished` y sus confirmaciones).
- Juez con otro modelo o con rúbricas múltiples; ejecución paralela de evals.

## Decisions

### D1. Layout de módulos y reglas de dependencia

```
tony/core/
  skills/
    models.py       SkillSpec {name, description, triggers, body, path}, SkillLoadError
    loader.py       load_skills(skills_dir) -> (list[SkillSpec], list[SkillLoadError]); parse_skill(path)
    index.py        skills_index(skills) -> str   ("Skills disponibles:\n- name: description")
    triggers.py     normalize(text) (NFKD sin acentos + casefold), matched_skills(text, skills), skill_blocks(text, skills) -> str
  subagents/
    permissions.py  ChildPolicy, child_policy(parent: ToolConfig, child: ToolConfig, parent_is_subagent) -> ChildPolicy
    builder.py      SubagentWorkerBuilder: catálogo efectivo, manager de servidores nuevos, runner del hijo
    launcher.py     SubagentLauncher(host: SubtaskHost | None, parent_id, subagents, limit=2): run_subagent(...)
    ports.py        SubtaskHost (Protocol): submit_subtask(parent_id, agent, request) -> Task; wait(task_id)
  loader/
    models.py       AgentSpec += skills, skill_errors, subagents, subagent_errors, parent
    loader.py       load_agent(path, settings, env, depth=0): carga skills/ y subagents/
    tooljson.py     read_tool_json, upsert_server, remove_server, write_tool_json (atómico, indent=2)
  mcp/
    generations.py  McpGenerationPool: current, acquire(), release(gen), swap(tool_config) -> Generation
  config/
    watcher.py      ConfigWatcher(agents_dir, on_change, watch=watchfiles.awatch): start(), stop()
  orchestrator/
    task.py         Task += agent: str | None; eventos SUBTASK_STARTED, SUBTASK_FINISHED
    orchestrator.py submit_subtask, children(task_id), deadline y gate compartidos, cascada
    ports.py        WorkerFactory += attach_host(host), release(task_id)
    worker.py       SdkWorkerFactory sobre McpGenerationPool; construye hijos vía SubagentWorkerBuilder
    reload.py       AgentReloader(agents_dir, settings, env, pool, events, notify): reload(agent)
  runner/
    native_tools.py NativeToolSet construye read_skill/run_subagent si el handler los implementa
    claude_sdk.py   ClaudeSdkRunner(..., native_handlers=None): servidor tony del worker
    prompt.py       build_system_prompt(+skills index), build_user_prompt(request, skills)
    front_prompt.py build_front_system_prompt(+skills index, read_skill)
    oneshot.py      one_shot(settings, model_alias, prompt, schema=None) -> str | dict  (SDK, max_turns=1)
  doctor/
    checks.py       CheckResult {name, ok: bool | None, detail, hint}; run_checks(paths, offline, connect)
    validate.py     validate_config(paths) -> list[CheckResult]  (sin red ni procesos; lo usa AgentReloader)
  evals/
    models.py       TaskEval, ConversationEval, TaskExpect, TurnExpect (pydantic)
    loader.py       load_task_evals(path), load_conversation_evals(path)
    replay.py       ReplayRunner(AgentRunner) y ReplayConversationRunner desde fixtures JSONL
    assertions.py   check_task(result, events, expect) -> list[str]; check_turn(reply, delegated, expect)
    judge.py        judge(one_shot, criterion, reply) -> Verdict {pass, reason}; JUDGE_PROMPT fijo
    recorder.py     RecordingConversationRunner (decora el runner real y escribe el fixture)
  logging/
    replay.py       read_events(path), render_events(events) -> str, to_eval(events, id) -> (yaml_entry, lines)
tony/apps/cli/
    mcp_cli.py      sub-app `mcp`: add (parse_add_tokens), remove, list
    agents_cli.py   sub-app `agents`: listado y show (YAML sin secretos)
    doctor_cli.py   `doctor` y sub-app `config validate`; render ✓/✗ y código de salida
    replay_cli.py   `replay`
    chat.py         composición: ConfigWatcher + AgentReloader + avisos al canal
evals/
    conftest.py, test_tareas.py, test_conversaciones.py, tareas.yaml, conversaciones.yaml, fixtures/, runs/ (ignorado)
tests/fakes/
    fake_filesystem_server.py (MCP stdio de ficheros sobre un directorio dado), fake_watch.py (awatch guionizado)
```

- Reglas nuevas en `tests/test_architecture.py`: `claude_agent_sdk` también permitido en `tony.core.runner.oneshot` (y solo ahí fuera de los cuatro adaptadores actuales); `watchfiles` solo en `tony.core.config.watcher`; `tony.core.evals` y `tony.core.doctor` no importan `pytest`, `typer` ni `claude_agent_sdk`; `tony.core.skills` y `tony.core.subagents` no importan `tony.core.channels`.
- `subagents` vive fuera de `orchestrator` porque la política de permisos y la construcción del hijo son reutilizables por cualquier anfitrión; el orquestador solo conoce `Task.agent` y la factoría.

### D2. Skills: índice, `read_skill` y triggers (decisión fijada)

- `SkillSpec` es un modelo pydantic estricto; `parse_skill` reutiliza `split_frontmatter`; validaciones: `name == carpeta`, `description` obligatoria y ≤ 200, `trigger: list[str]`.
- Índice = solo `name: description`; el cuerpo solo llega por `read_skill` o por coincidencia de `trigger`. Comparación de triggers: `unicodedata.normalize("NFKD")` + eliminación de marcas diacríticas + `casefold()` sobre texto y frase; coincidencia por subcadena. Un bloque por skill activada y por turno.
- Punto de inyección: `front` → `ChatSession.handle` construye `preamble + skill_blocks(message, front.skills) + message`; `worker` → `build_user_prompt(request, spec.skills)` antepone los bloques al `TaskRequest` JSON (texto evaluado: `objetivo + "\n" + contexto`).
- Handlers: `ChatSession.read_skill(name)` y `WorkerNativeHandlers.read_skill(name)` comparten `find_skill(skills, name)` en `skills/index.py`, que lanza `UnknownSkill` con la lista disponible; `NativeToolSet` la convierte en `text_reply(is_error=True)`.
- Alternativa descartada: pasar el cuerpo de todas las skills en el system prompt. Rechazada: contradice la decisión fijada y crece con cada skill.

### D3. Subagentes: política de permisos (decisión fijada)

- `child_policy(parent, child, parent_is_subagent) -> ChildPolicy {servers: dict[str, ServerSpec], new_servers: list[str], allow_parent, allow_child, confirm: list[str], warnings}`:
  - `child` vacío (`ToolConfig()` por defecto) → `servers = parent.mcpServers`, `allow_child = None`, `confirm = parent.confirm` (herencia exacta).
  - Servidores: los del padre siempre; los que solo declara el hijo se añaden a `new_servers` si `not parent_is_subagent`, en caso contrario se ignoran con advertencia; un nombre repetido usa la definición del padre.
  - `confirm = parent.confirm ∪ child.confirm`.
- El catálogo efectivo se calcula sobre tools reales, no sobre patrones: `ToolCatalog.build(tools_by_server, child.allow, confirm)` seguido de `catalog.restrict(parent.allow)` (nuevo método que filtra `refs` con el mismo `fnmatch`). Así `allow` ausente en el padre = todas, y `notion.*` del hijo nunca pasa si el padre dice `fs.*`.
- Alternativa descartada: intersección sintáctica de patrones. Rechazada: no es computable en general (`fs.*` ∩ `*.read_file`).

### D4. Subagentes: construcción y ejecución como subtarea (decisión fijada)

- `Task.agent: str | None` (None = `worker` configurado). `Orchestrator.submit_subtask(parent_id, agent, request)` = `submit(request, parent_id)` con `agent`; el orquestador implementa `SubtaskHost`. `SdkWorkerFactory.build_worker(task, …)`: si `task.agent` es None construye el `worker` como hoy; si no, resuelve `parent = tasks[task.parent_id]`, toma la generación arrendada por la raíz y llama a `SubagentWorkerBuilder.build(parent_spec, child_spec, generation, policy, gate, token)`.
- `SubagentWorkerBuilder`: tools del padre = `generation.manager` (ya conectado); tools nuevas del hijo = `McpManager` propio arrancado con `server_filter=new_servers`, parado en `release(task_id)`. `ToolCaller` compuesto: enruta por `ref.server` al manager que lo posee. Runner del hijo = `ClaudeSdkRunner(settings, task.id, gate, call, cancel_token, native_handlers=WorkerNativeHandlers(child_spec, launcher=None))` (sin `run_subagent`: profundidad 1).
- Historial propio: cada subtarea es un `ClaudeSDKClient` nuevo (como toda tarea). Modelo del hijo: `settings.models[child_spec.model]`.
- `SubagentLauncher(host, parent_id, subagents, limit=2)`: `asyncio.Semaphore(2)` por tarea padre; `run_subagent(name, request)`: nombre desconocido → `TaskResult error` listando disponibles; `host is None` → `TaskResult error` "solo en tony chat y web"; si no, `task = host.submit_subtask(parent_id, name, request)` y `await host.wait(task.id)`. Sin `wait_for` de 20 s (tool nativa, no pasa por `ToolProxyFactory`).
- El `worker` obtiene `native_handlers` en `SdkWorkerFactory.build_worker` (`WorkerNativeHandlers(spec, SubagentLauncher(self._host, task.id, spec.subagents))`); `Orchestrator.__init__` llama a `worker_factory.attach_host(self)` (nuevo método del puerto; `FakeWorkerFactory` lo registra).
- `ClaudeSdkRunner.run`: si `spec.tools.native ∩ {read_skill, run_subagent}` no es vacío y hay handlers, `build_options(..., native_server=NativeToolSet(native, handlers).build())` añade `tony` a `mcp_servers` y `mcp__tony__*` a `allowed_tools`. Las tools nativas emiten `tool.call`/`tool.result` con `tool = "tony.<nombre>"` a través de un envoltorio común en `NativeToolSet` (hoy el front no los emite; se añade para ambos y el `TaskEventSink` genera `task.progress`).
- Alternativa descartada: ejecutar el hijo "inline" dentro del proxy del padre sin orquestador. Rechazada: perdería cola, eventos, cancelación en cascada y exposición como hijo.

### D5. Deadline, puerta y eventos compartidos (decisión fijada)

- Deadline: `_run_until_deadline` usa `remaining = parent.started_at + task_timeout_s - clock.monotonic()` cuando `task.parent_id` no es None (mínimo 0). `cancel(parent)` y `_expire(parent)` iteran `children(parent)` no finales y aplican la misma transición y motivo antes de disparar el token del padre.
- Puerta: el hijo recibe `OrchestratorConfirmGate(self, child.id)`; `request_confirmation(child_id, request)` toma el cerrojo del owner raíz (`root_of(task_id)`), transiciona al hijo a `waiting_confirmation`, emite `task.needs_confirmation` en el bus del hijo y lo espeja en el bus del padre con `task_id: child.id` en el payload. Rechazo o caducidad → `cancel(child_id, not_confirmed)` solo del hijo; el padre recibe el `TaskResult` cancelado por `run_subagent`.
- `CliChannel` ya llama a `orchestrator.confirm(id, approved, tool, args)`; el registro resuelve por `confirmation_id`, así que no cambia.
- Eventos: `Event` y el registro JSONL añaden `parent_id` (solo presente en subtareas; `JsonlEventSink(logs_dir, task_id, secrets, parent_id=None)`), campo adicional compatible con el contrato `schema_version 1`. El bus del padre recibe `subtask.started {task_id, agent}` al arrancar el hijo y `subtask.finished {task_id, status}` en `_finish`. `Orchestrator.children(task_id) -> list[Task]`.
- `WorkerFactory.release(task_id)` se llama en `_finish` (libera la generación de la raíz o para el manager de servidores nuevos del hijo).

### D6. `tony run` sin subagentes

- `tony run` conserva su camino directo (decisión de la entrega 02); `WorkerNativeHandlers` se construye con `launcher=SubagentLauncher(host=None, …)`, de modo que `read_skill` funciona y `run_subagent` devuelve el `TaskResult` de error de la spec. Al arrancar, si el agente declara `run_subagent`, se imprime una advertencia en `stderr`.
- Alternativa: mover `tony run` al orquestador con un reenviador de confirmaciones. Rechazada por reabrir la decisión D4 de la entrega 02 y por su coste; queda como posible mejora cuando el canal web exista.

### D7. Generaciones de MCPs y hot reload (decisión fijada)

- `McpGenerationPool(manager_factory, settings)`: `Generation {id: int, tool_config, manager: ToolManager, leases: int, retired: bool}`; `current`; `acquire() -> Generation` (arranque perezoso de la primera; `leases += 1`); `release(gen)` (`leases -= 1`; si `retired and leases == 0` → `manager.stop()`); `swap(tool_config)`: arranca un manager nuevo, lo fija como `current`, marca la anterior `retired` y la para si `leases == 0`. Un cierre de generación nunca lanza.
- `SdkWorkerFactory` usa el pool: la raíz arrienda `current` en `build_worker` y lo libera en `release(task_id)`; los hijos usan la generación de su raíz (sin arriendo propio).
- `AgentReloader.reload(agent)`: `validate_config` para ese agente (sin red ni procesos) → en error, `events.emit("config.reload_failed", {agent, error})` + aviso; si es válido, `spec = load_agent(...)`, `factory.update_spec(spec)` (tools, secrets, skills, subagentes para tareas nuevas), `await pool.swap(spec.tools)`, `events.emit("config.reloaded", {agent, servers: list(spec.tools.mcpServers)})` + aviso. Las recargas de un mismo agente se serializan con un `asyncio.Lock`. Solo se recarga el agente resuelto como `worker` (y sus subagentes, que pertenecen a su carpeta); un cambio en la carpeta del `front` produce un aviso "requiere reinicio" sin evento.
- `ConfigWatcher(agents_dir, on_change, watch=watchfiles.awatch)`: tarea asíncrona sobre `awatch(agents_dir, stop_event=…)` con `watch_filter` que acepta solo rutas que terminan en `tool/tool.json`; agente afectado = primer segmento relativo a `agents_dir`; cambios del mismo lote se deduplican por agente. `watch` inyectable para probar con un generador guionizado; una prueba de integración usa `watchfiles` real sobre `tmp_path`.
- Composición en `tony chat`: `reloader = AgentReloader(...)`, `watcher = ConfigWatcher(agents_dir, reloader.reload)`; `start()` tras `session.start`, `stop()` en el `finally`. `tony run` no crea el observador.
- Alternativa descartada: reiniciar el `McpManager` compartido en caliente. Rechazada: cortaría tools en vuelo de las tareas en curso.

### D8. Edición de `tool.json` y comandos `mcp`

- `tooljson.py`: `read_tool_json(path) -> dict` (`{}` si no existe; JSON inválido → `ToolJsonError`), `upsert_server(data, name, server, allow, confirm, force)` y `remove_server(data, name)` como funciones puras sobre el dict (preservan claves desconocidas y el orden), `write_tool_json(path, data)` = `json.dumps(indent=2, ensure_ascii=False)` + `write_atomic` (reutiliza `tony.core.memory.atomic`, que se mueve a `tony/core/config/atomic.py` y se reexporta desde `memory` para no romper imports).
- `parse_add_tokens(tokens) -> AddRequest`: extrae `--agent`, `--allow`, `--confirm`, `--header`, `--env`, `--force` de cualquier posición; el primer token no opción antes de `--` es la URL; los tokens tras `--` (sin las opciones extraídas) son `command` y `args`. El comando Typer se declara con `allow_extra_args=True, ignore_unknown_options=True` y recibe `ctx.args`. Sin esto, Click trataría `--agent viernes` tras `--` como argumentos del servidor.
- Validación por conexión: `McpManager(connect_timeout_s).start(ToolConfig(mcpServers={name: server}, allow=...))` → `status()[name]`; `ready` → `nombre: N tools (allow: todas|patrones)`; `error` → advertencia. `tony mcp list` arranca un manager por agente con `server_filter` vacío (todos) salvo `--no-connect`.

### D9. `agents`, `doctor` y `config validate`

- `tony agents` usa `load_all` + `spec.subagents`/`subagent_errors`/`skill_errors`; tabla con anchos calculados (sin dependencias nuevas). `show` serializa `spec.model_dump(exclude={"secrets", "path"})` con `yaml.safe_dump(allow_unicode=True, sort_keys=False)` tras `redact(data, spec.secrets)` (que ya cubre `Authorization`).
- `doctor/checks.py`: cada comprobación es una función pura `-> CheckResult` con dependencias inyectadas (`which`, `stat`, `find_spec`, `python_version`, `probe_model`, `connect_mcp`); `run_checks(paths, offline, connect)` las compone. `ok=None` = informativa (extras de voz). `config validate` = `run_checks(offline=True, connect=False)` y es lo que `AgentReloader` invoca para un agente.
- Patrones de `allow`/`confirm` sin tool: se comprueban contra el catálogo real tras conectar (solo `doctor`); `config validate` los omite.
- Petición mínima al modelo: `one_shot(settings, "claude-haiku", "Responde OK", max_turns=1)` en `runner/oneshot.py` (único módulo nuevo con `claude_agent_sdk`), compartido por el juez de evals.

### D10. Evals

- Harness en `evals/` (pytest, parametrizado desde los YAML) sobre `tony.core.evals` (sin pytest). Fixture de tarea = JSONL con los eventos del runner más `task.result {result}` final; `ReplayRunner.run` reemite los eventos grabados al `EventSink` (salvo `task.result`) y devuelve el `TaskResult` grabado; nunca llama a tools.
- Fixture de conversación = una línea por turno `{turn, user, delegate: TaskRequest | null, task_result: TaskResult | null, reply: {display_text, speech_text}}`; `ReplayConversationRunner` llama a `handlers.delegate(request)` cuando `delegate` no es null (el orquestador usa un `FakeAgentRunner` con `task_result`), y devuelve `reply`. `RecordingConversationRunner` envuelve al runner real con `TONY_EVALS=1` y escribe ese formato en `evals/runs/<fecha>/<id>.jsonl`.
- Modo real: tareas con `ClaudeSdkRunner` + `McpManager` sobre `tests/fakes/fake_filesystem_server.py` (MCP stdio en proceso con `list_directory`, `read_file`, `search_files`, `write_file` con `destructiveHint`, `fail`) sobre un `tmp_path` sembrado; confirmaciones con `AutoConfirmGate(True|False)` según el eval; `JsonlEventSink(Path("evals/runs"), eval_id, secrets)`.
- Juez: `judge(one_shot, criterion, reply)` con `JUDGE_PROMPT` fijo y `schema={pass: bool, reason: str}`; se omite sin `TONY_EVALS=1`.
- `tony replay`: `read_events` valida JSON por línea; `render_events` formatea; `to_eval` deriva `agent` de `task.started.agent`, `objetivo/contexto/restricciones` de `task.queued` o del primer `task.started`, `status` de `task.result` y `tools_called_all` de los `tool.call`.
- Alternativa descartada: grabar las respuestas del SDK a nivel de mensajes (cassettes). Rechazada: acopla a la versión del SDK; los eventos de Tony son el contrato estable.

### D11. Estrategia de pruebas (sin red ni modelo real)

- Skills: `tests/core/skills/` (parser con casos de frontera: descripción 200/201, nombre ≠ carpeta, trigger ausente; índice; triggers con acentos/mayúsculas y varias skills; `read_skill` desconocida). `test_front_prompt.py` y `test_runner_options.py` ampliados (índice en el system prompt, bloques en la petición).
- Subagentes: `tests/core/subagents/test_permissions.py` con la tabla de intersección parametrizada, herencia de `confirm`, servidor nuevo permitido/filtrado/rechazado; `test_launcher.py` (desconocido, sin host, semáforo 2 con `FakeClock`); `tests/core/orchestrator/test_subtasks.py` con `FakeWorkerFactory` (deadline heredado, cascada de cancelación y timeout, confirmación del hijo espejada en el padre y rechazo que cancela solo al hijo, `children`, `subtask.*`, `parent_id` en JSONL).
- Loader: `tests/core/test_loader_skills_subagents.py` (skills, subagentes, roto, rol `front`, nivel 2 ignorado, `run_subagent` eliminado); `tests/agents/test_bundled_agents.py` ampliado (skill `resumen-web`, subagente `investigador`).
- Generaciones y recarga: `tests/core/mcp/test_generations.py` (arriendo, swap con y sin tareas, cierre al liberar, parada que no lanza); `tests/core/orchestrator/test_reload.py` (JSON inválido conserva la generación, `${VAR}` ausente, recarga válida emite `config.reloaded` y la tarea nueva ve el servidor nuevo); `tests/core/config/test_watcher.py` (filtro de rutas, agente afectado, subagente → padre, `agent.md` ignorado, con `awatch` guionizado y una prueba real sobre `tmp_path` con timeout de 5 s).
- `tool.json`: `tests/core/test_tooljson.py` (crear, preservar, `--force`, remove, fallo en `os.replace` inyectado); `tests/apps/test_cli_mcp.py` con `CliRunner`, `FakeManager` y el MCP stdio falso para `add`/`list`.
- Doctor: `tests/core/doctor/test_checks.py` (cada comprobación con dependencias inyectadas) y `tests/apps/test_cli_doctor.py` sobre `tmp_repo` con fallos inducidos (`--offline`, `config validate`).
- Evals: `tests/core/evals/` (modelos y YAML, `ReplayRunner`, aserciones, juez con `one_shot` falso, grabador); `tests/core/logging/test_replay.py` y `tests/apps/test_cli_replay.py` (render, `--to-eval`, fichero inválido); `evals/` en verde con fixtures.
- Sesión y CLI: `test_chat_session.py` ampliado (`read_skill`, trigger en el turno, aviso de recarga), `test_cli_chat.py` (observador arrancado y parado, `tony run` con advertencia de `run_subagent`).

## Risks / Trade-offs

- [El SDK puede invocar `run_subagent` varias veces en paralelo y agotar el deadline del padre] → semáforo de 2 por tarea y deadline compartido; el padre recibe `timeout` del hijo y decide.
- [Un servidor nuevo del hijo que tarda en arrancar (p. ej. `npx`) consume tiempo del deadline compartido] → `mcp_connect_timeout_s` acota la espera; se documenta que los servidores habituales deben declararse en el padre.
- [`watchfiles` emite varios eventos por una sola escritura (editor que escribe temporal + rename)] → deduplicación por agente dentro del lote y cerrojo por agente en `AgentReloader`; una validación fallida intermedia solo produce un `config.reload_failed` extra, nunca pierde la última válida.
- [Una generación retirada con tareas largas mantiene procesos MCP duplicados] → aceptado (acotado por `task_timeout_s`); `close()` del orquestador para todas las generaciones.
- [Opciones de `tony mcp add` tras `--` entran en conflicto con opciones del propio servidor (`--env`)] → documentado en `--help`; se recomienda `--env` antes de `--`.
- [`doctor` sin `--offline` consume una petición de modelo y arranca todos los MCPs] → es el uso previsto; `config validate` cubre pre-commit y hot reload.
- [Fixtures grabados quedan desfasados respecto al prompt del agente] → el fixture es el contrato de Tony (eventos), no del modelo; se regraban con `TONY_EVALS=1` y `tony replay --to-eval`.
- [Añadir `parent_id` al registro JSONL] → campo opcional y ausente en tareas raíz; los lectores existentes (replay, tests) lo ignoran.
- [Cambio del puerto `WorkerFactory` (`attach_host`, `release`)] → ambos con implementación trivial en `FakeWorkerFactory`; `tony run` no usa el puerto.

## Migration Plan

- Sin migración de datos: `skills/` y `subagents/` son opcionales; `tool.json` existentes siguen válidos; `.gitignore` añade `evals/runs/`.
- Despliegue local: `uv sync` → `uv run pytest` → `uv run tony doctor` → `uv run tony mcp add fetch -- npx -y @modelcontextprotocol/server-fetch --agent viernes` → `uv run tony chat` con la sesión de cierre → `uv run pytest evals/ -m evals`.
- Rollback: revertir el commit; `tony mcp remove fetch --agent viernes` deshace el alta de cierre; `evals/runs/` puede borrarse.

## Open Questions

- Si `watchfiles` en el sistema de ficheros del usuario entrega `Change.modified` o `Change.added` al guardar con editores que renombran; solo afecta al filtro (se aceptan ambos) y no a specs ni tareas.
- Si el modelo `claude-haiku` devuelve `structured_output` fiable para el juez con `max_turns=1`; si no, el juez cae a parsear el primer objeto JSON del texto, sin cambiar la interfaz.

## Desviaciones de implementación

- D4/D7: el `McpManager` compartido sigue siendo propiedad de una tarea asyncio dedicada (`ManagerOwner`, extraído de la revisión post-implementación de la entrega 02); cada `Generation` del `McpGenerationPool` y el manager propio de un subagente tienen su `ManagerOwner`, de modo que `swap` cierra la generación anterior desde la tarea que la abrió en vez de reiniciarla en sitio. La firma del `WorkerRunnerFactory` recibe un sexto argumento (`native_handlers`) y los protocolos `ToolManager`/`ManagerFactory` viven en `tony.core.mcp.ports`.
- D4: los handlers concretos del worker son `SkillToolHandlers` (solo `read_skill`, para subagentes) y `WorkerToolHandlers` (+ `run_subagent`) en `tony.core.subagents.handlers`; `NativeToolSet` construye cada tool solo si el agente la declara y los handlers la implementan.
- D5: `ChatSession` registra las subtareas en `active_task_ids` a partir de `subtask.started/finished` (Ctrl+C y `/cancel` llegan a los hijos) y reenvía la confirmación del hijo con su `task_id`; el espejo en el bus del padre no se escribe en el JSONL del padre. Se añade el evento `skill.activated {skill}` (runner y sesión) para que el log refleje los triggers.
- D7/D9: `AgentReloader` valida con `validate_agent` (`tony.core.doctor.validate`), la misma comprobación por agente que compone `run_checks`; `validate_config` es `run_checks(offline=True, connect=False)`.
- D10: `TaskEval` admite `confirm: bool` (respuesta automática a las confirmaciones del eval); el MCP `fetch` del cierre es `uvx mcp-server-fetch` (el paquete npm `@modelcontextprotocol/server-fetch` no existe); los prompts de `jarvis` (mensaje literal en `contexto`) y `viernes` (leer la skill que encaje) se ajustaron para que los triggers y `read_skill` se activen al delegar.
- 14.4: el commit se hace en `main` (instrucción de la entrega) en lugar de en una rama `feat/`.

## Revisión post-implementación

Decisiones cambiadas tras la revisión externa del código de esta entrega (sin cambiar los specs):

- D4/D7 (instantánea por tarea raíz): `SdkWorkerFactory` arrienda en `build_worker` el par `(spec, generación)` vigente y lo guarda por tarea raíz; los subagentes, sus permisos y sus secretos se resuelven desde esa instantánea, nunca desde la spec recargada. Cada hijo toma su propio arriendo sobre la generación heredada (`McpGenerationPool.lease`) y lo libera en `release(task_id)`, de modo que una generación retirada no se cierra mientras un hijo la use.
- D7 (recarga atómica): `AgentReloader` ya no publica la spec antes del `swap`; `SdkWorkerFactory.reload_spec(spec)` arranca la generación nueva y, solo cuando está lista, publica spec y generación juntas (`swap(tool_config, on_publish)`). Un fallo o una cancelación durante el arranque conserva ambas anteriores y emite `config.reload_failed` (motivo `recarga cancelada…` en el segundo caso).
- D7 (`McpGenerationPool`): los arranques iniciales concurrentes se serializan con un `asyncio.Lock` que no cubre el `swap`, para que una recarga nunca bloquee tareas nuevas; si un `swap` publica mientras arranca la primera generación, el arranque tardío pierde y se cierra. Los owners aún no publicados se registran y `close_all()` los para; un arranque que termina tras el cierre no publica (`RuntimeError` "el pool de MCPs se cerró durante el arranque").
- `ManagerOwner`: el consumidor espera el future compartido bajo `asyncio.shield`; si lo cancelan, el owner para el manager en cuanto termine de arrancar. `manager.stop()` se ejecuta siempre en un `finally` dentro de la tarea propietaria y el future solo se resuelve una vez.
- D5 (`Orchestrator`): un hijo cancelado en cascada antes de arrancar también pasa por `_finish` (resultado publicado, `subtask.finished`, `finished.set()`), así `wait(hijo)` siempre vuelve. Los fallos de `WorkerFactory.release` se registran con `warning` y nunca impiden señalar el final ni liberar la cola; el cierre del manager propio de un hijo tampoco propaga.
- D9 (`agents show`): la redacción usa `AgentSpec.all_secrets()` (secretos propios y de todos los subagentes); el registro JSONL del worker usa la misma lista y la factoría la acumula entre recargas para que las tareas antiguas sigan redactadas.
- D8 (`tool.json`): `mcp add`/`mcp remove` hacen lectura, edición y reemplazo bajo un lock entre procesos (`fcntl.flock` sobre el fichero hermano `tool.json.lock`, ignorado en git) mediante `edit_tool_json`.
- D10 (`task.started`): el runner registra el `TaskRequest` completo (`objetivo`, `contexto`, `restricciones`) redactado; `tony replay --to-eval` avisa en stderr ("petición incompleta en el registro…") cuando un registro antiguo no los incluye. `RecordingConversationRunner` trunca el fichero al abrir la sesión: cada grabación reemplaza la anterior en vez de concatenarla.
- D9 (`doctor` y `config validate`): `check_agents` falla explícitamente por cada agente configurado en `settings.front`/`settings.worker` cuya carpeta no existe.
- Composición de `tony chat`: `ChatRepl` acepta `before_close` y el observador de configuración se para antes de cerrar la sesión, para que ninguna recarga aterrice sobre un pool ya cerrado.
