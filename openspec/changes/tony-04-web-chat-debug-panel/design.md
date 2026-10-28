# Design

## Context

- Estado de partida (entregas 01–03): `ChatSession` (`tony/core/channels/session.py`) es el servicio de aplicación del front: `start(conversation_id)` abre el `ConversationRunner` con `resume`, `handle(text, modality)` resuelve el modo, construye el preámbulo, ejecuta el turno y envía `AssistantReply` por el puerto `Channel`; `delegate` encola en el `Orchestrator` y reenvía `TaskProgress`/`NeedsConfirmation`/`AssistantWait` al canal; `cancel_active()` cancela todas las tareas del turno e interrumpe al front; `close()` es idempotente. El puerto `Channel` (`ports.py`) solo tiene `send(ChannelMessage)` con `AssistantReply | AssistantWait | TaskProgress | NeedsConfirmation | Notice`.
- `Orchestrator`: `submit`, `confirm(confirmation_id, approved, tool, args)` (lanza `OrchestratorError` si es inválida), `cancel(task_id, reason)`, `events(task_id)` (historial + vivo, termina en `task.result`), `wait`, `tasks`, y tras la entrega 03 `submit_subtask`, `children(task_id)`, `subtask.started/finished` en el bus del padre, `parent_id` en `Event` y en el JSONL, `task.needs_confirmation` del hijo espejado en el padre. `task.finished {status, usage}` lo emite el runner al terminar (`usage_from_message`: `input_tokens`, `output_tokens`, `total_cost_usd`, `num_turns`), una vez por tarea.
- `ClaudeSdkConversation.turn()` devuelve `FrontTurn {text, structured, usage, error}` al final; usa `output_format` JSON e `include_partial_messages=False`, por lo que no existen fragmentos legibles de `display_text` durante el turno. `ConfirmGate.confirm(ConfirmRequest) -> bool` es la puerta de las tools del front; en la CLI es `CliConfirmGate` sobre `AnswerSource`.
- Composición CLI (`tony/apps/cli/chat.py::run_chat`): settings → `.env` → roles → memoria → `SdkWorkerFactory` → `Orchestrator` → canal + puerta → tools del front → runner del front → `JsonlEventSink("chat-<conversation_id>")` → `ChatSession` → `AsyncExitStack` (03 añade `AgentReloader` + `ConfigWatcher`). Hoy no está extraída y la web la necesita entera salvo canal, puerta y REPL.
- `TonySettings.web = WebSettings {host: "127.0.0.1", port: 8787}` y `Limits.token_alert = 50000` ya existen. `pyproject.toml` declara el extra `web = []` vacío. `.gitignore` ya ignora `node_modules/` y `tony/apps/web/frontend/dist/`.
- Reglas de arquitectura (`tests/test_architecture.py`): `tony.core` no importa `tony.apps`, `typer` ni `fastapi`; `runner`/`orchestrator`/`memory` no importan `channels`; `sqlite3` solo en `memory.conversations`.
- Dobles existentes: `FakeConversationRunner` (turnos guionizados que pueden llamar a los handlers nativos), `FakeWorkerFactory` + `ScriptedRunner` (pasos `tool`/`confirm`/`sleep`/`result`), `FakeClock`, `ListChannel`, `ListEventSink`.
- Motivación y alcance: ver proposal.md. Comportamiento exigido: ver `specs/*/spec.md` de este cambio.

## Goals / Non-Goals

**Goals:**
- `tony.apps.web` como adaptadores (Ports & Adapters) sobre `ChatSession` y `Orchestrator`: `WebChannel` implementa `Channel`, el enrutador de confirmaciones sustituye a `AnswerSource`, y la API HTTP solo traduce a llamadas del núcleo.
- Una sola composición CLI/web; `tony chat` y `tony web` difieren solo en canal, puerta de confirmación y bucle de entrada.
- Protocolo WS determinista y reproducible en pruebas sin red ni modelo: `seq`, búfer de reenvío, cola acotada, confirmaciones y `usage` probados con `TestClient`, `FakeConversationRunner`, `FakeWorkerFactory` y `FakeClock`.
- Núcleo extendido de forma mínima y compatible hacia atrás (campos con valor por defecto, parámetros opcionales, métodos nuevos).

**Non-Goals:**
- Streaming real de texto desde el SDK (ver D6: el gancho existe, el motor v1 no lo alimenta), audio/voz, varias conversaciones abiertas a la vez, autenticación, HTTPS, despliegue remoto.
- Reproducir en la web los comandos locales de la CLI (`/memoria`, `/salir`); la memoria se consulta por `GET /api/memory`.
- Persistir en SQLite los eventos de tarea reenviados; el JSONL sigue siendo la fuente para `tony replay`.

## Decisions

### D1. Layout de módulos y reglas de dependencia

```
tony/core/channels/
  ports.py        += UserAccepted {message_id, effective_mode}, AssistantDelta {message_id, text},
                     TaskEvent {task_id, parent_id, type, payload, seq, ts}; AssistantReply += message_id, usage
  session.py      emite UserAccepted/AssistantDelta/TaskEvent; turn(prompt, on_text=...)
  bootstrap.py    RuntimeOptions, ChatRuntime, build_chat_runtime(options, channel_factory, gate_factory, ...)
tony/core/memory/conversations.py  Message += id; add_message -> id; messages(); list_conversations(); has_conversation()
tony/core/orchestrator/worker.py   SdkWorkerFactory.status() -> dict[str, McpServerStatus]
tony/core/runner/conversation.py   ConversationRunner.turn(prompt, on_text=None); ClaudeSdkConversation acepta e ignora on_text en v1
tony/apps/web/
  server.py       create_app(runtime, web_options) -> FastAPI; serve(options); OriginPolicy (middleware HTTP + comprobación WS); estáticos
  api.py          APIRouter /api/*; manejadores de error -> {error, detail}
  protocol.py     PROTOCOL_VERSION, tipos de mensaje, Envelope (pydantic), parse_client_message(text) con límite 32 KiB,
                  ConversationStream (seq, ring buffer 500, OutboundQueue acotada 500 con coalescencia)
  ws_channel.py   WebChannel(Channel): ChannelMessage -> Envelope; TaskStreamer (suscripción a hijos, log_path); UsageTracker
  confirmations.py ConfirmationRouter (pendientes por confirmation_id, caducidad), WebConfirmGate(ConfirmGate) para el front
  hub.py          ConversationHub: una ChatSession abierta, socket activo por conversación, hello/attach/detach, turnos
  frontend/       package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html, src/, dist/ (ignorado)
tony/apps/cli/main.py  comando `web` (importa tony.apps.web.server de forma perezosa)
tony/apps/cli/chat.py  run_chat sobre build_chat_runtime (solo canal, puerta, dispatcher y REPL)
tests/apps/web/        helpers.py (build_test_app), test_*.py
```

- Reglas nuevas en `tests/test_architecture.py`: `fastapi`, `starlette` y `uvicorn` solo en `tony.apps.web`; `tony.apps.web` no importa `tony.apps.cli`; `tony.core.channels.bootstrap` no importa `typer`/`fastapi` (cubierto por la regla general de `tony.core`).
- `bootstrap.py` vive en `tony.core.channels` porque compone servicios del núcleo sin ningún framework; `tony.apps.cli` y `tony.apps.web` lo consumen. Alternativa descartada: duplicar la composición en `tony/apps/web/server.py` (dos lugares que divergen; la entrega 03 ya añade `AgentReloader` + `ConfigWatcher` a esa composición y la web debe heredarlos sin copiarlos).

### D2. Composición compartida: `build_chat_runtime`

- `RuntimeOptions {config_path, agents_dir, logs_dir, memory_dir}` (sustituye a los campos comunes de `ChatOptions`; `ChatOptions` conserva `new_conversation` y delega). `ChatRuntime` expone `settings, front, worker, memory, orchestrator, worker_factory, front_manager, secrets, session_log, reloader, watcher` y `open_session(conversation_id, channel) -> ChatSession` más `aclose()`.
- `build_chat_runtime(options, gate_factory, conversation_factory, manager_factory, runner_factory, watch_factory)`: `gate_factory(settings, secrets) -> ConfirmGate` crea la puerta del front (CLI: `CliConfirmGate`; web: `WebConfirmGate`). El canal se pasa en `open_session` porque la web crea el canal por conversación.
- El `JsonlEventSink("chat-<conversation_id>")` se abre en `open_session` y se cierra en `ChatRuntime.close_session()`; en la CLI hay una única sesión por proceso (como hoy); en la web el `ConversationHub` abre y cierra sesiones (D4).
- `run_chat` queda como: `runtime = await build_chat_runtime(...)`, `channel = CliChannel(...)`, `session = runtime.open_session(conversation_id, channel)`, `ChatRepl(...)`, `AsyncExitStack` con `runtime.aclose`. Comportamiento de `tony chat` sin cambios (las pruebas actuales de `test_cli_chat.py` siguen valiendo).
- Se aplica después de que la entrega 03 esté en `main`: el `AgentReloader`/`ConfigWatcher` que 03 añade a `run_chat` se mueve a `build_chat_runtime` y `notify` se conecta a `session.notify_reload` de la sesión abierta (en la web, a la sesión del hub).

### D3. Extensiones del núcleo (mínimas y compatibles)

- `ports.py`: tres mensajes nuevos y dos campos nuevos con valor por defecto (`AssistantReply.message_id: str | None = None`, `usage: dict[str, Any] = {}`). `ChannelMessage` amplía la unión; `CliChannel.send` ignora los tipos nuevos (rama `else: return`), así `ListChannel` y las pruebas actuales no cambian.
- `ChatSession.handle`: tras resolver el modo y `_store_message("user")` (que ahora devuelve `message_id`), envía `UserAccepted(message_id, mode.mode)`; llama a `self._runner.turn(prompt, on_text=self._on_text)` donde `_on_text(text)` envía `AssistantDelta(reply_message_id, text)`; el `message_id` de la respuesta se genera antes del turno (`uuid4().hex`) y se pasa a `add_message(..., message_id=...)` para que el id persistido coincida con el enviado en `assistant.final`. `AssistantReply` lleva `message_id` y `usage = turn.usage`. `FrontTurn.error` se expone en `AssistantReply.error: str | None` para que el canal web emita `error {code: "turn_failed"}`.
- `ChatSession._forward_events`: además de los mensajes actuales envía `TaskEvent(event.task_id, event.parent_id, event.type, event.payload, event.seq, event.ts)` por cada evento del flujo de la tarea raíz (con secretos ya redactados por `redact` antes de enviarlos). `TaskProgress` y `NeedsConfirmation` se mantienen para la CLI. Alternativa descartada: que `ChatSession` también se suscriba a los hijos; se deja al adaptador web (`TaskStreamer`) porque solo él necesita el detalle de los hijos y ya tiene el orquestador para `confirm`/`cancel`.
- `ConversationRunner.turn(prompt, on_text: Callable[[str], Awaitable[None]] | None = None)`: `ClaudeSdkConversation` acepta el parámetro y no lo invoca en v1 (D6); `FakeConversationRunner` lo invoca para los fragmentos de un turno guionizado (`FrontTurn.chunks: list[str]` opcional en el doble, no en el núcleo).
- `ConversationStore`: `Message.id`, `add_message(..., message_id: str | None = None) -> str`, `messages(conversation_id) -> list[Message]`, `list_conversations(limit=20) -> list[ConversationSummary {id, channel, created_at}]`, `has_conversation(id) -> bool`. Sin cambio de esquema.
- `SdkWorkerFactory.status() -> dict[str, McpServerStatus]`: `{}` si no hay generación arrancada; si no, `generation.manager.status()` (sobre el `McpGenerationPool` de 03). Solo lectura, sin arrancar nada.

### D4. `ConversationHub`: una sesión abierta, un socket activo

- Estado: `session: ChatSession | None`, `conversation_id`, `channel: WebChannel`, `stream: ConversationStream`, `socket: WebSocket | None`, `turn: asyncio.Task | None`, `router: ConfirmationRouter`.
- `hello(socket, conversation_id | None, last_seq)`: valida la conversación (`has_conversation`; `None` → `start_conversation("web")`); si es otra conversación y la actual está en reposo (sin socket, sin turno, sin tareas activas) cierra la sesión y abre la nueva; si la actual está ocupada → `conversation_busy`; si es la misma conversación y hay socket → `conversation_busy` + cierre 1008; si no, `attach(socket, last_seq)`: responde `hello.ok` con `state` (`turn_in_progress`, `active_tasks` desde `orchestrator.tasks` filtradas por `session.active_task_ids` y sus hijos, `pending_confirmation` desde el router con `expires_in_s` restante) y reenvía del ring buffer `seq > last_seq` (o `resync: true`).
- `user_text(text)`: si hay turno → `turn_in_progress`; si no, `turn = create_task(session.handle(text))`; al terminar el turno (éxito o excepción) el hub emite `usage {task_id: null}` y `assistant.final` a través del `WebChannel` (que ya recibió el `AssistantReply`), y `error {turn_failed}` si `reply.error`.
- `cancel(task_id)`: `task_id ∈ session.active_task_ids` → `session.cancel_active()`; si no, `orchestrator.cancel(task_id)` (`OrchestratorError` → `unknown_task`).
- Desconexión del socket: `detach()` deja el stream vivo (el turno y las tareas continúan; los eventos siguen entrando al ring buffer).
- Alternativa descartada: N sesiones abiertas con un `ClaudeSDKClient` cada una. Rechazada en v1: el orquestador solo ejecuta una raíz y el asistente es monousuario; añade memoria y conexiones sin beneficio hasta que exista el canal de voz.

### D5. `ConversationStream`: `seq`, búfer de reenvío y cola acotada (decisión fijada)

- `publish(type, payload, task_id=None, message_id=None) -> Envelope`: asigna `seq = last + 1`, construye el sobre `{v: 1, type, seq, conversation_id, message_id?, task_id?, payload}` y lo guarda en un `deque(maxlen=500)`; si hay socket, lo encola en `OutboundQueue`.
- `OutboundQueue` (capacidad 500): al estar llena antes de encolar, fusiona los `assistant.delta` pendientes del mismo `message_id` en uno (texto concatenado, conserva el `seq` del último) y, si sigue llena, espera (backpressure sobre el productor) hasta que el emisor consuma; nunca descarta eventos de otro tipo. El emisor es una `asyncio.Task` por socket que hace `await websocket.send_text(json)`.
- Reenvío: `replay(last_seq) -> list[Envelope]`; `resync` cuando `last_seq < buffer[0].seq - 1`.
- El `seq` por conversación vive en memoria del proceso; al reiniciar el servidor empieza en 0 y el cliente, al recibir `hello.ok.last_seq < su último visto`, reinicia su contador (regla del cliente: aceptar `seq` si `seq > last_seen` o si `hello.ok.last_seq < last_seen`, en cuyo caso `last_seen = hello.ok.last_seq`).

### D6. Streaming honesto en v1 (decisión fijada)

- `assistant.delta` forma parte del protocolo y del camino `on_text → AssistantDelta → WebChannel`, pero `ClaudeSdkConversation` no produce fragmentos: con `output_format` JSON y `include_partial_messages=False` el único texto legible es `structured_output.display_text` al final. Los `assistant.text` que el runner emite al JSONL durante el turno contienen el JSON del mensaje del asistente, no texto legible, y no se usan.
- Consecuencia visible: con el motor real, el cliente recibe `user.accepted`, eventuales `assistant.wait`/`task.*`/`tool.*`/`usage` y un único `assistant.final`. La UI está diseñada para ambos casos (deltas opcionales; `final` sustituye).
- Habilitar fragmentos reales queda para una entrega posterior (activar `include_partial_messages=True` y extraer `display_text` parcial del JSON en construcción) sin cambiar el protocolo ni la UI.

### D7. Confirmaciones: un enrutador para orquestador y front (decisión fijada)

- `ConfirmationRouter.register(confirmation_id, task_id, tool, args, resolver, timeout_s, now)` guarda la pendiente; `resolve(confirmation_id, approved, task_id=None)`: desconocida, caducada o con `task_id` distinto → `InvalidConfirmation`; si no, llama al `resolver(approved)` una vez y la retira. `pending() -> PendingView | None` para `hello.ok.state` con `expires_in_s = max(0, deadline - now)`.
- Orquestador: `WebChannel.send(NeedsConfirmation)` registra en el router con `resolver = lambda approved: orchestrator.confirm(id, approved, tool, args)` y publica `task.needs_confirmation` con `expires_in_s = limits.confirm_timeout_s`. `TaskEvent` de tipo `task.confirmed`/`task.cancelled`/`task.result` retira la pendiente de esa tarea. El orquestador sigue siendo quien valida id + tool + args y quien cancela por caducidad.
- Front: `WebConfirmGate(router, stream, timeout_s).confirm(request)` registra la pendiente con `task_id = "front"`, publica `task.needs_confirmation` (`task_id: "front"`) y espera un `Future` con `asyncio.wait_for(timeout_s)`; caducidad → `False`.
- HTTP `POST /api/tasks/{task_id}/confirm` y WS `confirm` llaman a `router.resolve(...)` (WS sin `task_id`: se resuelve por id); `OrchestratorError` del resolver → `invalid_confirmation`.
- Alternativa descartada: resolver solo por WS. Rechazada: el endpoint HTTP permite confirmar desde herramientas externas (curl) y simplifica las pruebas.

### D8. `WebChannel`, `TaskStreamer` y `UsageTracker`

- `WebChannel.send`: `UserAccepted` → `user.accepted`; `AssistantDelta` → `assistant.delta`; `AssistantWait` → `assistant.wait`; `AssistantReply` → `usage {task_id: null}` + `assistant.final {display_text, speech_text, message_id}`; `Notice` → `error {code: "notice", detail}`; `NeedsConfirmation` → D7; `TaskProgress` → ignorado (el `task.progress` llega como `TaskEvent`); `TaskEvent` → `TaskStreamer.forward(event)`.
- `TaskStreamer.forward`: publica el evento como `{type: event.type, task_id, payload}` con `parent_id` en el `payload` cuando no es `None`; en `task.queued` añade `log_path` (`logs_dir.glob("*/<task_id>.jsonl")`, `None` si no existe aún); en `subtask.started {task_id}` del padre arranca `asyncio.Task` que consume `orchestrator.events(child_id)` y reenvía con `parent_id`; en `task.finished` alimenta `UsageTracker` y publica `usage`; `task.result` de la raíz cancela los consumidores de hijos que queden.
- `UsageTracker.record(task_id, root_id, usage) -> UsagePayload`: suma `input_tokens + output_tokens` por raíz (`root_id` = `parent_id or task_id`); `alert = cumulative > limits.token_alert`; `cost_usd = total_cost_usd`.
- Eventos de recarga (`config.reloaded`/`config.reload_failed`) llegan a la sesión como `Notice` (03). Para distinguirlos, `ChatSession.notify_reload` envía además un `TaskEvent(task_id="config", type="config.reloaded"|"config.reload_failed", payload)`, que `WebChannel` publica con ese `type` sin `task_id`.

### D9. Servidor, política de `Origin`, límites y estáticos (decisión fijada)

- `OriginPolicy(host, port)`: `allowed = {f"http://{host}:{port}", f"http://localhost:{port}"} ∪ {f"http://127.0.0.1:{port}"} si host ∈ {localhost, 127.0.0.1}` (y `[::1]` si `host == "::1"`). Middleware HTTP: método en `{POST, PATCH, PUT, DELETE}` y `Origin ∉ allowed` (incluido ausente) → `403 {error: "forbidden_origin"}`. WebSocket: `websocket.headers["origin"]` ∉ allowed → `await websocket.close(code=1008)` tras responder 403 al handshake (`WebSocketDenialResponse`, soportado por Starlette para uvicorn con `websockets`).
- `--host` fuera de loopback sin `--allow-remote` → `typer.Exit(2)`; con él, advertencia en `stderr`. `--open` → `webbrowser.open` en un callback `startup`.
- Tamaño: `parse_client_message` mide `len(text.encode("utf-8")) > 32768` → `error {message_too_large}` + `close(1009)`. uvicorn se arranca con `ws_max_size = 65536` como segunda barrera.
- Estáticos: `StaticFiles(directory=dist/assets)` en `/assets` y `GET /` → `FileResponse(dist/index.html)` si existe; si no, `HTMLResponse(FALLBACK_PAGE)` (en español, con el comando de build). `dist` se localiza con `importlib.resources`/`Path(__file__).parent / "frontend" / "dist"`; el `wheel` no incluye `dist` (se compila en el checkout).
- Errores JSON: manejadores para `HTTPException` (`{error: detail.code, detail: detail.message}` mediante `ApiError(status, code, detail)`), `RequestValidationError` → `422 validation_error`, `404` genérico → `not_found`.
- Cierre: `serve()` instala manejadores de `SIGINT`/`SIGTERM` (uvicorn ya lo hace) y el evento `shutdown` de la app llama a `hub.aclose()` (cierra socket con 1001, cancela tareas, cierra la sesión) y `runtime.aclose()`.
- Alternativa descartada: CORS abierto con `CORSMiddleware`. Rechazada: no hace falta ningún origen cruzado; la lista cerrada de `Origin` es la barrera.

### D10. Comando `tony web` y dependencias

- `tony/apps/cli/main.py::web(port, host, open_browser, allow_remote, config, agents_dir)`: `from tony.apps.web.server import serve` dentro de un `try/except ImportError` → mensaje "Instala el extra web: uv sync --extra web" y `Exit(2)`. `serve` construye el runtime, la app y ejecuta `uvicorn.Server(Config(app, host, port, log_level="info", ws_max_size=65536)).serve()` en el bucle actual.
- `pyproject.toml`: `web = ["fastapi>=0.162,<1", "uvicorn[standard]>=0.30,<1", "websockets>=12,<16"]`; `dev += ["httpx>=0.27,<1"]` (cliente de `TestClient`). `uv sync --extra web` en el README.
- Las pruebas del backend importan `fastapi` directamente: se ejecutan con el extra instalado en el entorno de desarrollo (`uv sync --extra web --group dev`); `tests/apps/web/conftest.py` hace `pytest.importorskip("fastapi")` para que `uv run pytest` sin el extra siga en verde.

### D11. Frontend: estructura, protocolo en el cliente y saneado (decisión fijada)

- Stack: React 18.3.1, Vite, TypeScript estricto, Vitest + `@testing-library/react` + `jsdom`, `marked` + `dompurify`. Sin framework CSS: `src/styles.css` con variables (`--bg`, `--fg`, `--accent`, `--warn`, `--muted`) y bloque `@media (prefers-color-scheme: dark)`; `max-width: 80ch` en la columna de chat; `:focus-visible` con anillo; `@media (prefers-reduced-motion)`.
- `src/protocol/types.ts` (tipos del sobre y de cada `payload`), `src/protocol/reducer.ts` (reductor puro `reduce(state, envelope)`: descarte por `seq`, mensajes, streaming por `message_id`, árbol de tareas, tool calls emparejados, `usage` y alerta, confirmación pendiente con `deadline`, eventos de configuración), `src/protocol/socket.ts` (`ChatSocket`: apertura, `hello` con `last_seq`, reconexión cada 2 s con `setTimeout`, cola de salida vacía mientras está desconectado), `src/api/client.ts` (`fetch` con `credentials: "same-origin"` y errores `{error, detail}`).
- Componentes: `App`, `ChatList`, `MessageBubble` (markdown), `WaitBubble`, `ConfirmationCard` (cuenta atrás con `setInterval` 1 s), `Composer`, `ModeSelector`, `StatusBanner`, `DebugPanel` (`TaskTree`, `ToolList`, `UsageMeter`, `ReloadList`, botón "Copiar JSON" con `navigator.clipboard` y fallback `<textarea>`), `icons.tsx` (SVG inline).
- Markdown: `marked.parse(text)` → `DOMPurify.sanitize(html, {USE_PROFILES: {html: true}, FORBID_TAGS: ["style", "iframe", "object", "embed"], ADD_ATTR: ["target"]})` y un hook `afterSanitizeAttributes` que fija `rel="noopener noreferrer"` y `target="_blank"` en `<a>`. Alternativa descartada: `react-markdown`; aceptable, pero `marked` + `DOMPurify` tiene menos superficie y el saneado es explícito.
- Persistencia local: `localStorage` para `conversation_id` y el estado plegado del panel.
- `vite.config.ts`: `server.proxy` para `/api` y `/ws` (con `ws: true`) hacia `http://127.0.0.1:8787`, reescribiendo la cabecera `Origin` a `http://127.0.0.1:8787` en `configure` (`proxyReq`/`proxyReqWs`), ya que el servidor rechaza el origen `5173` del servidor de desarrollo. `build.outDir = "dist"`, `emptyOutDir: true`.
- `package.json` (`"private": true`): scripts `dev`, `build` (`tsc -b && vite build`), `test` (`vitest run`), `lint` (`tsc --noEmit`); versiones exactas (sin `^`) fijadas en el momento de `npm install`, y `package-lock.json` versionado. Node ≥ 20.

### D12. Estrategia de pruebas (sin red ni modelo real)

- Backend (`tests/apps/web/`), todo con `TestClient` (HTTP y `websocket_connect`) sobre `build_test_app(...)` de `helpers.py`, que compone `create_app` con `FakeConversationRunner`, `FakeWorkerFactory` (scripts por `objetivo`), `FakeClock` inyectado en orquestador y router, `tmp_path` para `memory/` y `logs/`, y `Origin` válido por defecto en el cliente:
  - `test_origin.py`: PATCH/POST/WS con `Origin` inválido o ausente → 403; GET sin `Origin` → 200; `localhost`/`127.0.0.1` equivalentes.
  - `test_api_settings.py`, `test_api_health.py`, `test_api_conversations.py`, `test_api_memory.py`, `test_api_tasks.py` (confirm 200/409 por id, tarea ajena y segunda respuesta; cancel 200/404).
  - `test_protocol.py`: `parse_client_message` (límite 32 768 exacto, `v` ≠ 1, JSON inválido, tipos reservados/desconocidos), `ConversationStream` (`seq`, `replay`, `resync`), `OutboundQueue` (coalescencia de deltas y conservación de `task.*`).
  - `test_ws_flow.py`: `hello` null/existente/desconocido, `hello_required`, turno completo con deltas (runner con `chunks`) y sin deltas, `turn_in_progress`, `empty_text`, `set_mode`, `usage` del front, `turn_failed`.
  - `test_ws_tasks.py`: delegación con `ScriptedRunner` (`task.*`, `tool.call/result`, `log_path`, `assistant.wait` con `FakeClock`), confirmación por WS y por HTTP, caducidad a 60 s con `FakeClock`, cancelación, subtarea con `parent_id` y `usage` acumulado con alerta.
  - `test_ws_reconnect.py`: desconexión tras `seq` 18 y reconexión con `last_seq: 18` → solo 19..25; estado con `pending_confirmation.expires_in_s`; `resync`; `conversation_busy` para el segundo socket y relevo tras cierre.
  - `test_hub.py`: cambio de conversación en reposo y ocupada; `aclose` cancela tareas y cierra con 1001.
  - `test_server_static.py`: `dist` presente/ausente; `test_cli_web.py` (`CliRunner`): extra ausente, `--host` remoto sin/con `--allow-remote`, agente inexistente, `--open` con `webbrowser.open` inyectado.
- Núcleo: `tests/core/channels/test_chat_session.py` ampliado (`UserAccepted`, `AssistantDelta` vía `on_text`, `TaskEvent` por evento, `message_id` coherente con SQLite, `usage` en la respuesta); `tests/core/memory/test_conversations.py` (`add_message` devuelve id, `messages`, `list_conversations`, `has_conversation`); `tests/core/orchestrator/test_worker_factory.py` (`status()` vacío y arrancado); `tests/core/channels/test_bootstrap.py` (composición con dobles, `open_session` y `aclose`); `tests/apps/test_cli_chat.py` sigue en verde sin cambios de comportamiento.
- Frontend (Vitest, `jsdom`): `reducer.test.ts` (descarte por `seq`, deltas + final sin duplicar, árbol con hijos y estados, emparejado de tools, `usage` y alerta, confirmación caducada por `deadline`, `resync`), `socket.test.ts` (reconexión a 2 s con temporizadores falsos y `hello` con `last_seq`), `markdown.test.ts` (HTML crudo neutralizado, `rel`/`target`), `DebugPanel.test.tsx`, `ConfirmationCard.test.tsx` (cuenta atrás y botones), `ModeSelector.test.tsx` (`fetch` simulado, éxito y 422), `Composer.test.tsx` (`Enter`/`Shift+Enter`/prefijos).
- Mutación (≤ 3 min): `tony/apps/web/{protocol,confirmations,ws_channel,hub}.py` y los métodos nuevos de `conversations.py`; `server.py`/`api.py` quedan cubiertos por pruebas de integración y fuera del análisis de mutación por su coste.

## Risks / Trade-offs

- [El motor real no entrega fragmentos y la UI parece "sin streaming"] → documentado en D6 y en el README; la UI muestra `user.accepted` inmediato, la burbuja de espera y el progreso de tools, que es lo que el usuario percibe como actividad.
- [Confirmación del front con `task_id: "front"` no aparece en el árbol de tareas] → la `ConfirmationCard` se muestra igual; el panel la lista bajo "Front" sin nodo de tarea.
- [Cambios concurrentes con la entrega 03 en `session.py`, `chat.py` y `worker.py`] → este cambio se aplica sobre `main` con 03 integrada; las extensiones son aditivas (campos con defecto, métodos nuevos) y `build_chat_runtime` absorbe la composición final de 03.
- [Reiniciar el servidor reinicia `seq`] → regla del cliente en D5 (`hello.ok.last_seq` menor que el último visto reinicia el contador) y recarga del historial por HTTP.
- [Backpressure de `OutboundQueue` puede frenar el turno si el navegador no lee] → solo tras 500 eventos pendientes y coalescencia; el emisor por socket evita bloquear el bucle; si el socket muere, `detach` descarta la cola y el turno continúa.
- [`Origin` reescrito por el proxy de Vite solo en desarrollo] → `vite.config.ts` documenta que es exclusivo de `npm run dev`; en producción el navegador sirve desde el mismo origen.
- [`glob` de `log_path` en cada `task.queued`] → una llamada por tarea sobre `logs/<fecha>/`; coste despreciable.
- [`TestClient` ejecuta la app en un hilo con su propio bucle; `FakeClock` y tareas asyncio deben crearse dentro de la app] → `build_test_app` crea el runtime en el evento `startup` y expone los dobles por `app.state`.
- [`dompurify` en `jsdom` y en navegador] → se importa `dompurify` (detecta `window`); en Vitest con `environment: "jsdom"` funciona sin adaptador.

## Migration Plan

- Sin migración de datos: el esquema SQLite no cambia; `memory/settings.json` conserva su formato; `logs/` igual.
- Despliegue local: `uv sync --extra web` → `cd tony/apps/web/frontend && npm install && npm run build` → `uv run tony web --open` → sesión de cierre (chat, delegación con confirmación por botón, cambio de modo por botón, panel con tools y tokens).
- Rollback: revertir el commit; `tony chat` no depende de nada nuevo salvo `bootstrap.py`, que se revierte con el resto; borrar `tony/apps/web/frontend/node_modules` y `dist` si se desea.

## Desviaciones de implementación

- D2: `gate_factory(settings, front)` recibe la `AgentSpec` del front en lugar de `secrets` (la puerta de la CLI necesita el nombre del agente; ninguna puerta usa los secretos). `build_chat_runtime` acepta `clock` (inyectado en orquestador y sesión) y `err`; `ChatRuntime.close_session()` cierra la sesión con `ChatSession.close(close_orchestrator=False)` para que el hub cambie de conversación sin cerrar el orquestador; `ChatSession.close()` sin argumentos sigue cerrándolo (CLI).
- D3/D8: `AgentReloader.notify(text, event_type, payload)` entrega además el evento de recarga y `ChatSession.notify_reload(text, event_type=None, payload=None)` lo reenvía como `TaskEvent(task_id="config")`; `ChatSession` envía `TaskEvent` antes de `TaskProgress`/`NeedsConfirmation` y el adaptador web ignora los `task.needs_confirmation` del flujo (usa `NeedsConfirmation`, que ya lleva el `task_id` del hijo).
- D4/D5: `hello.ok` y los `error` de petición (`hello_required`, `bad_envelope`, `unknown_type`, `turn_in_progress`, `empty_text`, `invalid_reply_mode`, `invalid_confirmation`, `unknown_task`, `conversation_busy`) viajan fuera de banda con `seq: 0` y no se reenvían en la reconexión; el cliente acepta `seq: 0` siempre y descarta `seq ≤ último visto` para el resto. `ConversationStream.publish` es `async` (backpressure de `OutboundQueue`); el `hello.ok` sale antes de adjuntar la cola y el reenvío se precarga con `OutboundQueue.prefill`.
- D7: la puerta del front (`WebConfirmGate`) publica además `task.confirmed`/`task.cancelled {reason: "not_confirmed"}` con `task_id: "front"` para que la tarjeta desaparezca; `stream` es un atributo que el hub reasigna al abrir cada conversación.
- D8: `usage {task_id: null}` del turno lleva `cumulative_tokens` (entrada + salida del turno) por simetría; el `mcp.status` del worker se reenvía como cualquier otro evento.
- D9: `OriginPolicy.allows` acepta `http://[::1]:<port>` solo cuando `host` es `::1`; las respuestas `405` usan `error: "method_not_allowed"`. El rechazo del WS con `Origin` ajeno se hace con `close(1008)` antes de `accept()` (Starlette responde 403 al handshake).
- D10: `WebOptions` vive en `tony/apps/web/options.py` (sin FastAPI) para que `tony web` valide host y puerto antes de importar el servidor; `serve(options)` construye el runtime en el bucle actual y después arranca uvicorn, así `front: nadie` termina con código 2 sin abrir el puerto.
- D11: `marked` 18 + `dompurify` 3 con `img`/`svg` también prohibidos (ninguna imagen remota); `typescript` 5.9 (la 7.x es la variante nativa, no la de referencia); el cliente trata `assistant.final` sin deltas previos como mensaje nuevo.
- D12: `tests/apps/web/helpers.py` construye el runtime de dobles dentro del `startup` del `TestClient` y expone `advance`/`settle` sobre su portal; `test_api_tasks.py` y los tres ficheros de flujo comparten `open_chat`/`drain_until`/`send`.

## Open Questions

- Si `uvicorn`+`websockets` en la versión resuelta devuelve el 403 del handshake con `WebSocketDenialResponse` o solo cierra la conexión; en ambos casos el `hello` nunca se acepta y la prueba comprueba el rechazo antes de cualquier mensaje. No afecta a specs ni tareas.
- Si la versión de `marked` resuelta expone `marked.parse` síncrono con las opciones por defecto; si devolviera `Promise`, se usa `marked.parse(text, {async: false})`. No afecta a specs ni tareas.
