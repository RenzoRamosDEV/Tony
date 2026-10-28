# Design

## Context

- Estado actual (entrega 01, en `main`): `tony.core.{config,loader,mcp,runner,logging}` y `tony.apps.cli` con `tony run`. Puertos estables que esta entrega reutiliza sin cambiar su firma: `AgentRunner.run(spec, request, tools, events)`, `EventSink.emit(type, payload)`, `ConfirmGate.confirm(ConfirmRequest) -> bool`, `McpManager.start/call/status/stop`, `ToolCatalog`, `TaskRequest`/`TaskResult`. `ToolProxyFactory` + `TaskState` son la barrera de ejecución; `ClaudeSdkRunner` envuelve `ClaudeSDKClient` por tarea.
- Motivación y alcance: ver proposal.md. Comportamiento exigido: ver `specs/*/spec.md` de este cambio.
- Hechos verificados del SDK 0.2.174: `ClaudeSDKClient` mantiene una sesión persistente (`connect`, `query`, `receive_response`, `interrupt`, `session_id`/`resume`); `output_format` con JSON Schema produce `structured_output`; `create_sdk_mcp_server` crea servidores MCP en proceso; los alias `claude-haiku-5-5` y `claude-sonnet-5-5` funcionan.
- Hallazgos de la revisión de la entrega 01 que esta entrega resuelve por diseño: la cancelación debe ser una barrera real comprobada antes de cada tool; las confirmaciones deben serializarse (una visible por conversación) y ligarse a id+tarea+tool+args normalizados; los prompts de CLI van a `stderr`; un lector de `stdin` bloqueado no debe impedir la salida; el deadline de tarea debe cubrir toda la vida de la sesión del SDK.
- Otro agente corrige en paralelo hallazgos de revisión en `proxy.py`, `claude_sdk.py`, `manager.py`, `catalog.py`, `confirm_gate.py`, `redact.py` y el manejo de errores del loader/config. Esta entrega asume las firmas actuales como estables y añade comportamiento, no lo reescribe.

## Goals / Non-Goals

**Goals:**
- `tony.core.orchestrator`, `tony.core.memory` y `tony.core.channels` sin dependencias de CLI ni frameworks; la CLI es un adaptador fino.
- El canal es un puerto: la entrega 03 (web) implementa `Channel` y reutiliza `ChatSession`, orquestador, memoria y modo de respuesta sin tocarlos.
- El `worker` sigue ejecutándose por el mismo `ClaudeSdkRunner`; el `front` lo hace por un adaptador de conversación que comparte `build_options`-like, proxies y `can_use_tool`.
- Toda la lógica probable con dobles en proceso y reloj inyectable; suite < 60 s.

**Non-Goals:**
- Streaming de `display_text` al usuario (la salida estructurada llega completa al final; `assistant.text` solo se registra).
- Persistir la cola entre procesos, reintentos, prioridades, varias conversaciones simultáneas por proceso.
- Resumen automático de `preferences.md`; voz; web; subagentes (`parent_id` se acepta y persiste, pero su planificación detallada es de la entrega 04).

## Decisions

### D1. Layout de módulos y reglas de dependencia

```
tony/core/
  orchestrator/
    task.py          Task (id, parent_id, request, status, created/started/finished, result), TaskStatus, Event
    state.py         TRANSITIONS, transition(task, to) bajo asyncio.Lock por tarea
    queue.py         TaskQueue (deque, max_queued=10, una raíz activa)
    events.py        TaskEventBus (historial + suscriptores), TaskEventSink (EventSink → JSONL + bus + task.progress)
    confirm.py       ConfirmationRegistry (pendientes por owner), OrchestratorConfirmGate (ConfirmGate)
    cancel.py        CancelToken (asyncio.Event + reason)
    clock.py         Clock (monotonic, sleep), SystemClock
    worker.py        WorkerFactory: resuelve settings.worker, McpManager compartido, construye runner por tarea
    orchestrator.py  Orchestrator: submit, confirm, cancel, events, wait, close
    errors.py        OrchestratorError(code): queue_full, unknown_task, invalid_confirmation, invalid_transition
  memory/
    preferences.py   PreferencesStore(path, max_lines)
    settings.py      SettingsStore(path), UserSettings {reply_mode}
    conversations.py ConversationStore(sqlite_path)
    atomic.py        write_atomic(path, text)
  channels/
    ports.py         Channel (Protocol), mensajes: AssistantReply, AssistantWait, TaskProgress, NeedsConfirmation
    session.py       ChatSession (servicio de aplicación del front: turno, delegate, wait phrase, memoria)
  runner/
    cancel.py        (ver D5; TaskState pasa a envolver CancelToken)
    conversation.py  ConversationRunner (Protocol), ClaudeSdkConversation (adaptador), build_front_options
    native_tools.py  NativeToolHandlers (Protocol), build_native_server(native, handlers) -> McpSdkServerConfig
    front_prompt.py  build_front_system_prompt, build_turn_preamble
    reply_mode.py    strip_prefix, resolve_reply_mode, EffectiveMode, FrontReply, parse_front_reply
tony/apps/cli/
    chat.py          comando chat: composición (settings → specs → Orchestrator → ChatSession → REPL)
    chat_channel.py  CliChannel (Channel): stderr para prompts/progreso, stdout para respuestas
    stdin_reader.py  StdinReader: hilo daemon + asyncio.Queue; readline(prompt) cancelable
    repl.py          ChatRepl: bucle, comandos locales, prefijos, Ctrl+C
```

- Reglas (ampliación de `tests/test_architecture.py`): `tony.core.*` no importa `tony.apps`, `typer`, `fastapi`; `tony.core.runner.*`, `tony.core.orchestrator.*` y `tony.core.memory.*` no importan `tony.core.channels` (RF-01 por construcción); `claude_agent_sdk` solo en `runner.claude_sdk`, `runner.proxy`, `runner.conversation`, `runner.native_tools`; `sqlite3` solo en `memory.conversations`.
- `ChatSession` vive en `channels` porque es el único componente del core que habla con un `Channel`; así la regla "runner/orchestrator no importan channels" es verificable por paquete, no por excepción de módulo.
- Alternativa descartada: colocar `ChatSession` en `orchestrator`. Rechazada porque obligaría a excepciones módulo a módulo en la prueba de arquitectura y mezclaría el camino del `worker` con el del canal.

### D2. Orquestador: cola, estados y cerrojos (decisión fijada)

- Una tarea raíz (`parent_id=None`) en `running` a la vez; `max_queued=10`; la 11.ª → `OrchestratorError("queue_full")`. Las subtareas (`parent_id` de una tarea en `running`) no ocupan el hueco raíz y se ejecutan de inmediato; `parent_id` desconocido o en estado final → `unknown_task`.
- `TRANSITIONS = {queued: {running, cancelled}, running: {waiting_confirmation, done, failed, cancelled, timeout}, waiting_confirmation: {running, cancelled, timeout}}`; estados finales sin salidas. `transition()` toma `task.lock` (un `asyncio.Lock` por tarea), valida, asigna estado y marca de tiempo, y emite el evento correspondiente dentro del cerrojo para que el orden de eventos coincida con el de estados.
- El cerrojo protege solo la transición (microsegundos). La ejecución del runner nunca se hace bajo el cerrojo; por eso `confirm()` y `cancel()` siempre progresan aunque el runner esté bloqueado en una tool o en el SDK.
- Planificador: `submit` encola y llama a `_pump()`; `_pump()` arranca la siguiente raíz si no hay ninguna activa, en una `asyncio.Task` propia (`_run_task`). `_run_task` = `transition(running)` → carrera `runner.run()` vs `clock.sleep(task_timeout_s)` vs `cancel_token.wait()` → mapear resultado/estado → `task.result` → `_pump()`.
- Resultado tardío: si al terminar `runner.run()` la tarea ya está en estado final (cancelada o expirada), el `TaskResult` del runner se descarta y se conserva el resultado sintetizado por el orquestador.
- Alternativa descartada: un `asyncio.Lock` global del orquestador. Rechazada: una confirmación o cancelación de una subtarea no debe esperar a la transición de otra tarea.

### D3. Eventos: un bus por tarea alimentado por el mismo `EventSink`

- `TaskEventSink(jsonl: JsonlEventSink, bus: TaskEventBus)` implementa `EventSink`: escribe cada evento en el JSONL y lo publica en el bus; cuenta los `tool.call` y publica además `task.progress {tool, step}`. El runner del `worker` recibe exclusivamente este sink (RF-01).
- `TaskEventBus`: lista `history` + conjunto de `asyncio.Queue` suscriptoras. `events(task_id)` reproduce `history` y luego consume su cola hasta ver `task.result`; `task.result` cierra el bus (los suscriptores reciben un centinela).
- `Event {task_id, type, payload, seq, ts}`; `seq` y `ts` los asigna el bus con el mismo helper `utc_timestamp` del log, de modo que el JSONL y el bus coinciden línea a línea.
- Alternativa descartada: que el orquestador lea el JSONL para reconstruir eventos. Rechazada: acopla a disco y a formato; el bus en memoria es suficiente para un proceso único.

### D4. Confirmación gestionada por el orquestador (decisión fijada)

- `ConfirmationRegistry`: `pending: dict[confirmation_id, Pending {owner_id, request: ConfirmRequest, future}]`, un `asyncio.Lock` por `owner_id` (tarea o turno del front) que serializa solicitudes: una segunda tool del mismo owner espera a que la primera se resuelva, luego "una confirmación visible por conversación" se cumple porque solo hay una raíz activa y una pendiente por owner.
- `OrchestratorConfirmGate.confirm(request)`: adquiere el cerrojo del owner → `transition(waiting_confirmation)` → registra `pending` → emite `task.needs_confirmation {confirmation_id, tool, args}` (args originales; la clave usa `args_normalized`) → espera la `future` con `clock` hasta `confirm_timeout_s`. Aprobada: `transition(running)`, `task.confirmed {approved: true}`, devuelve `True`. Rechazada o caducada: `task.confirmed {approved: false}`, `orchestrator.cancel(task_id, reason="not_confirmed")`, devuelve `False` (el proxy existente produce el error `Tool <tool> no confirmada por el usuario` y el `TaskResult` `cancelled`).
- `Orchestrator.confirm(confirmation_id, approved)`: busca `pending`; si no existe, ya está resuelta, su tarea está en estado final o `tool`/`args_normalized` difieren del pendiente → `OrchestratorError("invalid_confirmation")` sin efecto. `confirm()` acepta opcionalmente `tool` y `args` para que los canales que los reenvían (web) validen la coincidencia; la CLI envía los recibidos en el evento.
- `cancel()` y el timeout de tarea resuelven la `future` pendiente con `False` e invalidan el id (`task.confirmed` no se emite en ese caso; se emite `task.cancelled`/`task.result`).
- `tony run` conserva `CliConfirmGate`; solo `tony chat` usa la puerta del orquestador.
- Alternativa descartada: resolver la confirmación en el canal (como en `tony run`). Rechazada: el canal web y la voz necesitan el mismo id, la misma validación y la misma caducidad; centralizarlo en el core evita tres implementaciones.

### D5. Cancelación y deadline como barrera real (modifica `runner`)

- `tony.core.runner.cancel.CancelToken {event: asyncio.Event, reason: str | None}`; `TaskState` lo incorpora (`TaskState.cancelled` pasa a delegar en el token; `cancel(reason)` conserva la semántica actual de "no confirmada" usando `reason=tool`). `ClaudeSdkRunner.__init__` acepta `cancel_token: CancelToken | None = None` (por defecto crea uno propio: `tony run` no cambia).
- `ToolProxyFactory._execute`: primera comprobación `if state.cancelled: emit tool.result{ok: false, error: "Tarea cancelada"}; return error` — antes de `allow`, confirmación y ejecución.
- `ClaudeSdkRunner.run`: `asyncio.timeout(task_timeout_s)` envuelve también `async with client` (conexión incluida); además espera en paralelo `cancel_token.wait()` y, al dispararse, llama a `client.interrupt()` y devuelve `cancelled` con `errores: ["cancelada por el usuario"]` (motivo `user`) o el motivo recibido. El orquestador aplica su propio deadline con `clock` como segunda defensa (el del runner es el que corta la conexión; el del orquestador garantiza el estado aunque el runner no responda).
- `Orchestrator.cancel(task_id, reason)`: bajo el cerrojo de la tarea, si está en `queued` la retira de la cola y la pasa a `cancelled` con `TaskResult` sintetizado; si está en `running`/`waiting_confirmation`, dispara el token, resuelve la confirmación pendiente con `False`, transiciona a `cancelled` y emite `task.cancelled {reason}`; en estado final no hace nada. El `task.result` se emite cuando `_run_task` termina (o inmediatamente si la tarea estaba en cola).
- Alternativa descartada: cancelar con `asyncio.Task.cancel()` sobre la tarea del runner. Rechazada: deja al cliente del SDK sin `interrupt()` y rompe el `finally` del proxy; el token coopera con el runner y la barrera del proxy es determinista.

### D6. Reloj inyectable y timeouts

- `Clock` (Protocol): `monotonic() -> float`, `async sleep(seconds)`. `SystemClock` delega en `time.monotonic`/`asyncio.sleep`. Toda espera con límite del orquestador (`confirm_timeout_s`, `task_timeout_s`, los 3 s de `wait_phrase`) se implementa como carrera `asyncio.wait({espera, clock.sleep(limit)}, FIRST_COMPLETED)`.
- `tests/fakes/clock.py` `FakeClock`: `advance(seconds)` resuelve los `sleep` cuyo vencimiento se alcanza; las pruebas de caducidad (60 s), timeout (300 s) y frase de espera (3 s) no duermen de verdad.
- Límites fijados: tool 20 s (no aplica a `delegate`), confirmación 60 s → `cancel(reason="not_confirmed")`, tarea 300 s desde `running` incluyendo esperas y conexión.

### D7. Front en modo conversación (decisión fijada)

- `ConversationRunner` (Protocol, `tony.core.runner.conversation`): `async open(spec, catalog, native_server, events) -> None`, `async turn(prompt: str) -> FrontTurn {text: str, structured: dict | None, usage}`, `async interrupt()`, `async close()`, `session_id: str | None`. `FakeConversationRunner` en `tests/fakes/conversation.py` guioniza respuestas y puede invocar los handlers nativos (p. ej. `delegate`) para simular la decisión del modelo.
- `ClaudeSdkConversation`: un `ClaudeSDKClient` por sesión de chat, abierto en `open()` y cerrado en `close()`; `turn()` = `query(prompt)` + `receive_response()`; captura `session_id` del primer `ResultMessage`. Si el cliente muere, el siguiente `turn()` reabre con `resume=session_id` (mismo identificador estable).
- Opciones (`build_front_options`): mismas defensas que el `worker` (`tools=[]`, `disallowed_tools`, `permission_mode="default"`, `setting_sources=[]`, `can_use_tool` que deniega todo lo no `mcp__`), `mcp_servers = {"tony": servidor nativo} ∪ proxies de sus MCPs declarados`, `allowed_tools = ["mcp__tony__*", "mcp__<server>__*"...]`, `max_turns = spec.max_steps`, `output_format` = esquema de `FrontReply {display_text: str, speech_text: str | null}`, `include_partial_messages=True` (solo para log).
- Bloque dinámico: como el `system_prompt` se fija al abrir el cliente persistente, se divide en dos: (a) `build_front_system_prompt(spec, native)` = `agent.md` + persona + zona horaria + catálogo de tools nativas + criterio de delegación (RF-02) + contrato de salida; (b) `build_turn_preamble(now, mode, preferences_block)` = fecha/hora, modo efectivo con su `style` y el bloque de preferencias (releído), antepuesto al texto del usuario en cada `turn()` dentro de un bloque `<contexto_del_turno>`. Así "preferences.md releído en cada turno" y "modo efectivo por mensaje" se cumplen sin reiniciar el proceso del SDK.
- Alternativa descartada: reconectar el cliente en cada turno con `resume=session_id` para refrescar el `system_prompt`. Rechazada: añade ~1–2 s de arranque de proceso por mensaje; se reserva como camino de recuperación.
- El turno del front no tiene deadline propio: lo acotan `max_turns`, el timeout de la tarea delegada (300 s) y la cancelación por `Ctrl+C`/`/cancel`, que interrumpe el cliente del front además de cancelar la tarea.

### D8. Tools nativas y `delegate`

- `build_native_server(native: list[str], handlers: NativeToolHandlers) -> McpSdkServerConfig` crea `create_sdk_mcp_server("tony", "1.0.0", tools)` con solo las tools listadas en `tool.json.native` (`read_skill`/`run_subagent` se ignoran con advertencia hasta la entrega 04). Esquemas: `delegate {objetivo: str, contexto?: str, restricciones?: list[str]}`, `remember {texto: str}`, `set_reply_mode {modo: enum}`.
- `NativeToolHandlers` (Protocol): `async delegate(request: TaskRequest) -> TaskResult`, `async remember(text) -> str`, `async set_reply_mode(mode) -> str`. Lo implementa `ChatSession`; el runner no conoce orquestador ni memoria.
- `ChatSession.delegate(request)`: `task = orchestrator.submit(request)` (si `queue_full` → `TaskResult(status="error", errores=["queue_full"])`), arranca un reenviador `events(task.id) → channel` (`task.progress`, `task.needs_confirmation`), arranca el temporizador de `wait_phrase` (3 s con `clock`; se cancela si llega el resultado antes; se emite como máximo una vez por tarea), `result = await orchestrator.wait(task.id)`, `conversations.record_task(...)` con `usage` de `task.finished`, devuelve `result.model_dump_json()`. Sin `wait_for` de 20 s: las tools nativas no pasan por `ToolProxyFactory`.
- `remember`: `PreferencesStore.append(text)` y respuesta `Guardado: - [fecha] texto`. `set_reply_mode`: valida y `SettingsStore.set_reply_mode`; el modo del turno en curso no cambia (ya está fijado).

### D9. Memoria

- `PreferencesStore(path, max_lines=settings.limits.memory_max_lines)`: `read()` filtra líneas en blanco; `append(text, today=date.today())` escribe `- [YYYY-MM-DD] text` vía `write_atomic` (`tempfile.NamedTemporaryFile(dir=path.parent)` + `os.replace`); `injection_block()` = cabecera `(…N líneas anteriores omitidas; ejecuta /memoria para verlas)` + últimas `max_lines` si procede. Sin resumen ni truncado del fichero (v1 sin pérdida de datos).
- `SettingsStore(path)`: `load() -> UserSettings` (pydantic, `reply_mode: ReplyMode | None`); JSON inválido o valor fuera de dominio → `UserSettings()` + `logging.warning`; `set_reply_mode(mode)` → `write_atomic`. Tipado para que la entrega 03 añada campos sin cambiar el formato.
- `ConversationStore(sqlite_path)`: `sqlite3` estándar, `PRAGMA journal_mode=WAL`, esquema creado en `__init__` con `CREATE TABLE IF NOT EXISTS`; ids `uuid4().hex`; fechas ISO-8601 UTC. Las operaciones son síncronas y cortas; `ChatSession` las ejecuta en el loop (volumen de un usuario). `last_conversation(channel)` sirve para continuar la última conversación de la CLI.
- Alternativa descartada: `aiosqlite`. Rechazada: dependencia extra para escrituras de milisegundos.

### D10. Modo de respuesta

- `strip_prefix(text) -> (prefix | None, text)`: reconoce `/v`, `/t`, `/b` al inicio seguidos de espacio o fin; `/t` sin texto es un error de uso que el canal muestra.
- `resolve_reply_mode(prefix, settings_store, yaml_default, input_modality) -> EffectiveMode {mode: voice|text|both, source: prefix|settings|yaml}` aplicando prefijo > `settings.json` > `tony.yaml`; `auto` → `voice` si `input_modality == "audio"`, `text` en caso contrario. Se evalúa una vez por mensaje y el valor viaja con el turno.
- `style_instruction(spec.style, mode)`: `voice` → `style.voice`; `text` → `style.text`; `both` → ambos + "produce `speech_text` como resumen hablado y `display_text` completo".
- `parse_front_reply(structured, fallback_text, mode) -> FrontReply`: valida con pydantic; en `text` fuerza `speech_text=None`; sin JSON válido → `{display_text: fallback_text, speech_text: None}`.

### D11. Canal y sesión de chat

- `Channel` (Protocol): `async send(message: ChannelMessage)`; mensajes tipados: `AssistantReply {display_text, speech_text, mode}`, `AssistantWait {text}`, `TaskProgress {task_id, tool, step}`, `NeedsConfirmation {task_id, confirmation_id, tool, args}`, `Notice {text}`. Las decisiones de presentación (stderr/stdout, `🔊`) son del adaptador.
- `ChatSession(front_runner, orchestrator, memory, channel, settings, clock)`: `start(conversation_id)` abre el runner; `handle(text, modality="text") -> AssistantReply`: `strip_prefix` → `resolve_reply_mode` → `add_message(user)` → `turn(preamble + text)` → `parse_front_reply` → `add_message(assistant)` → `channel.send(AssistantReply)`; `cancel_active()` cancela la tarea activa y llama a `front_runner.interrupt()`; `close()` cierra runner y orquestador (que para el `McpManager`).
- El `worker` nunca ve `channel`: solo `TaskEventSink`; `ChatSession` es quien reenvía eventos del bus al canal.

### D12. Composición y CLI

- `tony chat`: `load_settings` → `load_env` → `load_agent(agents_dir / settings.front)` y `load_agent(agents_dir / settings.worker)` (advertencia en `stderr` si `spec.role` no coincide con el rol asignado; error 2 si el agente no existe o no carga) → `Orchestrator(worker_factory, clock, limits)` → `ChatSession` → `ChatRepl.run()`. Factorías inyectables a nivel de módulo (`conversation_factory`, `manager_factory`, `runner_factory`) como en `tony run`.
- `WorkerFactory`: un `McpManager` por proceso, arrancado perezosamente en la primera tarea y detenido en `close()`; por tarea construye `JsonlEventSink`, `TaskEventSink`, `CancelToken`, `OrchestratorConfirmGate` y `ClaudeSdkRunner(settings, task_id, gate, manager.call, cancel_token)`.
- `StdinReader`: un único hilo `daemon=True` que hace `sys.stdin.readline()` y encola líneas en una `asyncio.Queue` vía `loop.call_soon_threadsafe`; `readline()` del lado asyncio es cancelable y comparte el mismo hilo para el prompt `tú> ` y para `[s/N]`. Al salir no se espera al hilo (daemon), por lo que una lectura bloqueada nunca retiene el proceso. Alternativa descartada: `asyncio.to_thread(input)` (hilos del executor no daemon: la salida se bloquea hasta que llega una línea).
- `ChatRepl`: `SIGINT` manejado con `loop.add_signal_handler`: primera señal con tarea activa → `session.cancel_active()` y aviso; segunda señal (o sin tarea) → `stop()`; `/salir` y EOF cierran ordenadamente (`session.close()` con timeout de 2 s, después salida forzada).
- `CliChannel`: `AssistantReply` → `stdout` (`🔊 <speech_text>` + `display_text` en `voice`/`both`); `AssistantWait`, `TaskProgress` (`· <tool>`), `Notice` → `stderr`; `NeedsConfirmation` → pregunta `[s/N]` por `stderr`, lee con `StdinReader` y llama a `orchestrator.confirm(id, approved, tool, args)`; si recibe `invalid_confirmation` (caducada) muestra el aviso de cancelación.

### D13. Estrategia de pruebas (sin red ni modelo real)

- Dobles nuevos en `tests/fakes/`: `FakeClock`, `FakeConversationRunner` (guion de turnos; puede llamar a `handlers.delegate/remember/set_reply_mode`), `ScriptedRunner` (`AgentRunner` que ejecuta un guion de pasos: `tool`, `confirm(tool, args)`, `sleep`, `raise`, `result`, consultando el `cancel_token`), `ListChannel`, `FakeStdin` (cola de líneas), SQLite en `tmp_path`.
- Orquestador: todos los casos de `specs/task-orchestrator` y `specs/tool-confirmation` con `ScriptedRunner` + `FakeClock` (cola llena, orden, subtarea, transiciones, confirmación válida/inválida/caducada/doble, cancelación en cola/espera/tool larga, timeout con confirmación pendiente, excepción del runner, suscripción tardía, varios consumidores, JSONL con `task.result` último).
- Runner: `test_runner_proxy.py` (barrera de cancelación), `test_runner_result.py` (timeout en conexión, cancelación externa) con el cliente falso existente; `test_conversation_options.py` (`build_front_options`), `test_native_tools.py` (catálogo según `native`, esquemas, `delegate` sin `wait_for`), `test_front_prompt.py`, `test_reply_mode.py` (tabla parametrizada prefijo × ajustes × yaml × modalidad; parseo de `FrontReply`).
- Memoria: `test_preferences.py` (append atómico con fallo inyectado en `os.replace`, límite 200/205, relectura), `test_settings.py` (ausente, corrupto, fuera de dominio, escritura), `test_conversations.py` (esquema, 45→40 mensajes, tarea con coste, última conversación por canal).
- Sesión: `test_chat_session.py` (hora no delega / PRs delega / front sin delegate, frase de espera una vez con `FakeClock`, tarea rápida sin frase, progreso y confirmación reenviados, `TaskResult` nunca llega crudo al canal, `set_reply_mode` no cambia el turno en curso, persistencia de turno).
- CLI: `test_cli_chat.py` con `CliRunner`, `FakeStdin`, `FakeConversationRunner` y `FakeManager` (comandos locales, prefijos, `--new`, advertencia de rol, `[s/N]` por `stderr`, salida `🔊`, código 2 por agente inexistente); `test_stdin_reader.py` (lectura cancelable, salida sin esperar al hilo); `Ctrl+C` probado enviando `SIGINT` al propio proceso dentro del loop con `FakeStdin` bloqueado.
- Arquitectura: `test_architecture.py` amplía las reglas de D1.

## Risks / Trade-offs

- [El `system_prompt` persistente no puede cambiar por turno] → el contexto variable va en el preámbulo del turno (D7); el bloque estable va en el `system_prompt`. Riesgo residual: el modelo podría tratar el preámbulo como texto del usuario; se mitiga con un bloque delimitado y una instrucción explícita en el `system_prompt`.
- [`output_format` JSON impide el streaming legible de `display_text`] → la CLI imprime al final (no-goal explícito); el log conserva `assistant.text`.
- [El modelo puede pedir varias confirmaciones en paralelo] → serializadas por owner en `ConfirmationRegistry`; la segunda espera dentro de su proxy y consume tiempo del deadline de tarea (aceptado).
- [`interrupt()` no detiene al instante] → la barrera del proxy rechaza toda tool tras la cancelación y el orquestador descarta resultados tardíos; el estado final lo fija el orquestador.
- [`npx` del MCP `filesystem` tarda en arrancar en la primera tarea] → `McpManager` compartido por proceso (arranque único por sesión de chat); `mcp_connect_timeout_s` configurable.
- [`SIGINT` con `loop.add_signal_handler` no funciona en Windows] → fuera de alcance (`uv run tony` en Linux); fallback a `KeyboardInterrupt` documentado.
- [SQLite en el loop puede bloquear milisegundos] → volumen de un usuario; si creciera, `asyncio.to_thread` sin cambiar la API.
- [Un `delegate` de hasta 300 s mantiene ocupado el turno del front] → progreso y `wait_phrase` mantienen informado al usuario; `Ctrl+C`/`/cancel` cancelan y el front recibe `cancelled` para redactar la respuesta.
- [Mutación de `proxy.py`/`claude_sdk.py` en paralelo por otro agente] → esta entrega añade un token y una comprobación al inicio de `_execute` y amplía el alcance del `asyncio.timeout`; se rebasa sobre `main` antes de empezar y se conservan las firmas públicas.

## Migration Plan

- Sin migración de datos: `memory/` se crea al primer uso; `conversations.sqlite` se crea con el esquema completo (`CREATE TABLE IF NOT EXISTS`).
- `tony run` conserva su comportamiento; los cambios en `proxy.py`/`claude_sdk.py` son compatibles (parámetro opcional y comprobación adicional).
- Despliegue local: `uv sync` → `uv run pytest` → `uv run tony chat` con la sesión de cierre (recordar preferencia, hora sin tarea, listar `.md`, borrado con confirmación caducada).
- Rollback: revertir el commit de la entrega; `memory/` puede eliminarse sin efectos (está ignorado por git).

## Open Questions

- Si el SDK entrega `session_id` en el `SystemMessage` de inicialización además de en `ResultMessage`; solo afecta a cuándo se captura el id (no a specs ni tareas).
- Si conviene acortar `max_turns` del `front` cuando no tiene `delegate`; se decide al observar la sesión de cierre y no cambia el diseño.

## Revisión post-implementación

Decisiones que cambiaron tras la revisión externa del código de esta entrega:

- **`StdinReader` por marca de tiempo (D12).** Cada línea se sella con `time.monotonic()` en el hilo lector y `readline()` solo acepta líneas tecleadas después de iniciarse. Un `s` escrito sin pregunta visible, o en respuesta a una pregunta abandonada, nunca aprueba una confirmación posterior; el tipeo anticipado entre prompts se descarta (comportamiento aceptado).
- **Un cerrojo de confirmación por conversación (D4/D12).** `CliConfirmGate` (front) y `CliChannel` (worker) comparten el mismo `asyncio.Lock`: solo hay una pregunta `[s/N]` visible y su lectura va dentro del cerrojo. La respuesta sigue validándose en el orquestador por id + tool + args.
- **Distribuidor de stdin durante el turno (D12).** `StdinDispatcher` posee stdin mientras `ChatSession.handle()` corre: `/cancel` cancela las tareas del turno, una línea con confirmación pendiente es su respuesta (vía `AnswerSource`, la única fuente de líneas de ambas puertas) y cualquier otra línea se rechaza con «Espera a que termine la tarea.». Una línea que llega justo al terminar el turno se reserva para el prompt. Las pruebas con `FakeStdin` modelan la pausa de tecleo con un `float`.
- **El turno enviado nunca se reenvía (D7).** `ClaudeSdkConversation.turn()` solo reintenta con reconexión si la excepción ocurre antes de `query()`. Si falla después, devuelve un `FrontTurn` con `error` y texto en español de resultado desconocido, emite `turn.error` en el JSONL del chat y marca el cliente como muerto: la reconexión con `resume` ocurre al siguiente turno. Un `ResultMessage.is_error` también produce un turno fallido explícito (`subtype: detalle`), nunca el último texto del asistente como respuesta válida.
- **Estado de cancelación por turno en el front (D5/D7).** `ToolProxyFactory` acepta un proveedor de `TaskState`; la conversación crea un `TaskState` nuevo por turno con `interrupt` conectado al cliente. Rechazar una tool solo invalida ese turno.
- **Una tarea propietaria del `McpManager` compartido (D12).** `SdkWorkerFactory` arranca el manager en una `asyncio.Task` dedicada (`_ManagerOwner`) que también lo detiene al recibir la señal de cierre (`close()` espera hasta `CLEANUP_BUDGET_S`), porque las sesiones MCP ligan su cancel scope a la tarea que las abrió. `McpManager.stop()` registra con `warning` los errores de cierre en vez de silenciarlos.
- **Deadline desde `running` y limpieza acotada (D2/D5).** El temporizador de tarea arranca antes de `build_worker()`; la supervisión compite `build+run` contra el deadline y el token de cancelación. Si el runner no coopera, tras `CLEANUP_BUDGET_S` (5 s, el mismo del runner) se cancela su tarea asyncio y se publica igualmente el `task.result` terminal, liberando el hueco raíz.
- **Conjunto de tareas del turno y supervisor de `delegate` (D8/D11).** `ChatSession.active_task_ids` sustituye al campo único; `cancel_active()` cancela todas. `delegate` registra la tarea al encolarla (`queued`) y, si el handler se cancela, cancela la tarea con `reason="front_interrupted"` y un supervisor independiente registra su estado final. La pregunta de confirmación se envía en una tarea aparte que se cancela cuando la tarea termina o se cancela, de modo que `delegate()` nunca queda bloqueado en stdin.
- **Redacción antes de persistir (D9).** `ChatSession` recibe la unión de secretos (`.env` + front + worker), redacta mensajes, `request` y `result` antes de SQLite y devuelve al front el `TaskResult` ya redactado; el JSONL del chat usa la misma unión.
- **Liberación de recursos (D11/D12).** `ChatRepl.run()` cierra la sesión en su `finally`; `ChatSession.close()` es idempotente y llega al orquestador aunque falle el front; `run_chat` usa `AsyncExitStack` para intentar cada cierre.
- **`sdk_session_id` persistido (D7/D9).** `conversations.sdk_session_id` (con migración `ALTER TABLE` para bases existentes) guarda el `session_id` del SDK tras cada turno; `start()` abre con `resume=` y, si falla, avisa por el canal y empieza de cero.
- **Contenido no confiable en el prompt (D7/D8).** Las preferencias se escapan (`<`/`>`) y se etiquetan como «datos, no instrucciones», igual que el bloque de resultado de `delegate`; `remember` rechaza textos con las etiquetas del bloque de contexto.
