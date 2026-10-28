# Proposal

## Why

Tony solo se usa hoy desde la terminal (`tony chat`): sin streaming visible, sin botones para confirmar tools o cambiar el modo de respuesta, y sin forma de ver qué hace Viernes (tool calls, subagentes, tokens) salvo leyendo el JSONL. La fase 2 se cierra cuando se puede usar el chat web a diario sin tocar código: hace falta un servidor local (FastAPI + WebSocket) que exponga la sesión de chat ya existente y una web de chat con panel de debug (RF-20) y cambio de modo por botón (F2).

## What Changes

- Nuevo paquete `tony.apps.web` (extra `tony[web]`: `fastapi`, `uvicorn`, `websockets`): servidor uvicorn arrancado con `tony web [--port 8787] [--host 127.0.0.1] [--open] [--allow-remote]`, escucha solo en loopback por defecto, valida `Origin` en toda petición HTTP mutante y en el upgrade del WebSocket (403 si no coincide), sirve el frontend compilado desde `/` y una página mínima si no está compilado.
- API HTTP JSON: `GET /api/health`, `GET|PATCH /api/settings` (persiste `reply_mode` en `memory/settings.json`), `POST /api/tasks/{task_id}/confirm`, `POST /api/tasks/{task_id}/cancel`, `GET /api/conversations`, `GET /api/conversations/{id}/messages`, `GET /api/memory`; errores siempre `{error, detail}`.
- WebSocket `/ws/chat` con protocolo JSON versionado (`v: 1`), `seq` monótono por conversación, reconexión sin texto duplicado, un solo socket activo por conversación (`conversation_busy`), cola de salida acotada a 500 eventos con coalescencia de `assistant.delta`, mensajes de texto ≤ 32 KiB y tipos de audio reservados para la entrega de voz.
- El canal web (`WebChannel`) implementa el puerto `Channel` sobre la misma `ChatSession` y el mismo orquestador que la CLI; la confirmación por botón (HTTP y WS) resuelve la misma confirmación pendiente del orquestador y de la puerta del `front`, sustituyendo a la lectura de `stdin`.
- Extensiones pequeñas del núcleo para alimentar la web sin romper la CLI: mensajes de canal `UserAccepted`, `AssistantDelta` y `TaskEvent`; `message_id` y `usage` en `AssistantReply`; callback opcional de fragmentos de texto en `ConversationRunner.turn`; `add_message` devuelve el id y el historial expone `list_conversations`/`messages`/`has_conversation`; `SdkWorkerFactory.status()` para `/api/health`; composición compartida CLI/web extraída de `run_chat`.
- Frontend React 18 + Vite + TypeScript en `tony/apps/web/frontend` (sin framework CSS; variables CSS y modo oscuro por `prefers-color-scheme`): chat con markdown saneado y streaming, burbuja de espera, bloque de confirmación con cuenta atrás de 60 s, botón de cancelar tarea, selector de modo (`auto | voice | text | both`), estados vacío/desconectado/error con reconexión automática cada 2 s, y panel de debug plegable (árbol de tareas con subagentes, tool calls con duración y error, tokens y coste, alerta "Tarea > 50 k tokens", ruta del JSONL, eventos `config.reloaded`, botón "Copiar JSON").
- Build e integración: `package.json` con `npm run dev` (proxy a `127.0.0.1:8787`), `npm run build` (genera `dist`, ya ignorado por git) y `npm test` (Vitest + Testing Library); dependencias npm fijadas en `package-lock.json`; sección nueva del README.

## Capabilities

### New Capabilities
- `web-server`: arranque de `tony web` (uvicorn, loopback por defecto, `--allow-remote`, `--open`), política de `Origin`, límites de tamaño y de cola, servicio del frontend compilado y página de respaldo, ciclo de vida de la sesión de chat web.
- `web-api`: endpoints HTTP JSON (salud, ajustes, confirmación y cancelación de tareas, conversaciones y mensajes, memoria) y su formato de error.
- `ws-chat-protocol`: protocolo WebSocket `v: 1` de `/ws/chat`: sobre, tipos de mensaje cliente/servidor, `seq` por conversación, reconexión y reenvío de estado, socket único por conversación, coalescencia de deltas, `usage` con alerta, tipos de audio reservados.
- `web-ui-chat`: interfaz de chat (mensajes con markdown saneado, streaming, espera, confirmación en línea con cuenta atrás, cancelar tarea, entrada con `Enter`/`Shift+Enter`, prefijos `/v /t /b`, selector de modo, estados de conexión) y requisitos de accesibilidad y diseño.
- `web-ui-debug-panel`: panel lateral de debug (árbol de tareas raíz/hijos con estado, tool calls, tokens y coste por tarea y acumulados por conversación, alerta de 50 k tokens, ruta del JSONL, eventos de recarga, copiar JSON).

### Modified Capabilities
- `user-memory`: la requirement "Operaciones del historial" añade `list_conversations(limit=20)`, `messages(conversation_id)`, `has_conversation(id)` y el retorno del `id` en `add_message` (el esquema SQLite no cambia).

## Impact

- Código nuevo: `tony/apps/web/{server,api,protocol,ws_channel,confirmations,hub}.py`, comando `web` en `tony/apps/cli/main.py`, frontend en `tony/apps/web/frontend/` (fuentes, tests, `package.json`, `package-lock.json`, `vite.config.ts`).
- Núcleo tocado de forma acotada y compatible hacia atrás: `tony/core/channels/{ports,session}.py`, `tony/core/runner/conversation.py` (parámetro opcional), `tony/core/memory/conversations.py`, `tony/core/orchestrator/worker.py` (`status()`), composición compartida en `tony/core/channels/bootstrap.py` usada por `tony/apps/cli/chat.py` y por el servidor web. `CliChannel` ignora los mensajes de canal nuevos; ninguna firma existente cambia de forma incompatible.
- Dependencias: extra `tony[web]` (`fastapi`, `uvicorn`, `websockets`) y `httpx` en el grupo `dev` (cliente de pruebas de FastAPI); Node/npm solo para compilar el frontend. `uv run tony chat` y `uv run tony run` siguen funcionando sin el extra.
- Pruebas: `tests/apps/web/` con `TestClient` y dobles existentes (`FakeConversationRunner`, `FakeWorkerFactory`/`ScriptedRunner`, `FakeClock`); suite Vitest del frontend; `tests/test_architecture.py` amplía las reglas (`fastapi`/`starlette`/`uvicorn` solo en `tony.apps.web`; `tony.apps.web` no importa `tony.apps.cli`).
- Depende de la entrega anterior (skills, subagentes, hot reload, `tony doctor`): el panel usa `subtask.started/finished` y `parent_id`, y el canal reenvía `config.reloaded`/`config.reload_failed`. Fuera de alcance: audio/voz, autenticación multiusuario, HTTPS, despliegue remoto.
