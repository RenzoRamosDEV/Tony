# Proposal

## Why

Tras la entrega 01, Tony solo ejecuta tareas sueltas con el `worker` (`tony run viernes "<tarea>"`): no hay nadie que converse con el usuario, decida cuándo delegar, recuerde preferencias ni coordine confirmaciones y cancelaciones entre el canal y el `worker`. Esta entrega construye esa capa intermedia (orquestador + Jarvis conversacional + memoria + `tony chat`) de forma que el canal web y la voz de las entregas siguientes solo tengan que implementar un puerto de canal.

## What Changes

- Nuevo paquete `tony.core.orchestrator`: cola de tareas (una raíz activa, máximo 10 en espera), máquina de estados `queued → running → (waiting_confirmation → running)* → {done, failed, cancelled, timeout}` con transiciones atómicas, eventos de tarea consultables como flujo asíncrono, puerta de confirmación propia (`confirmation_id` de un solo uso ligado a tarea, tool y argumentos normalizados, caducidad 60 s), cancelación externa y timeout de tarea de 300 s que cubre toda la vida de la sesión del motor.
- Nuevo modo conversación del runner para el agente `front`: cliente persistente por sesión de chat, servidor MCP en proceso `tony` con las tools nativas `delegate`, `remember` y `set_reply_mode` (solo las declaradas en `tool.json.native`), salida estructurada `{display_text, speech_text | null}` y decisión de delegar guiada por prompt (responder directo a conversación, conocimiento general, hora/fecha y preferencias; delegar cuando hacen falta datos externos, ficheros, acciones o herramientas).
- Aislamiento del `worker` por construcción: el `worker` solo recibe un sumidero de eventos (JSONL + orquestador); nunca una referencia al canal. El usuario solo ve `TaskResult` a través de la respuesta redactada por el `front`.
- Nuevo paquete `tony.core.memory`: `memory/preferences.md` (líneas `- [YYYY-MM-DD] texto`, escritura atómica, relectura en cada turno, inyección limitada a las últimas 200 líneas sin resumen automático), `memory/settings.json` (ajustes tipados, lectura tolerante) y `memory/conversations.sqlite` (conversaciones, mensajes y tareas con tokens y coste).
- Resolución del modo de respuesta efectivo: prefijo `/v` `/t` `/b` (solo ese mensaje) > `settings.json` > `tony.yaml`; `auto` → `voice` si la entrada fue audio, `text` si fue texto; inyección de `style.voice`/`style.text` según el modo; en `voice`/`both` `speech_text` es un resumen hablado sin markdown, tablas ni código.
- Frase de espera (`wait_phrase`) emitida una sola vez al canal si una tarea delegada no termina en 3 s, sin llamada extra al modelo; reenvío de `task.progress` y `task.needs_confirmation` al canal mientras la tarea sigue.
- Nuevo puerto de canal `tony.core.channels` (mensajes `assistant.reply`, `assistant.wait`, `task.progress`, `task.needs_confirmation`) y nuevo comando `tony chat`: REPL asíncrono (`tú> `), comandos locales `/mode`, `/memoria`, `/cancel`, `/salir`, confirmaciones `[s/N]` por `stderr`, `Ctrl+C` cancela la tarea activa (segundo `Ctrl+C` sale), persistencia de cada turno, opciones `--config`, `--agents-dir`, `--new`. En CLI `voice`/`both` degradan a texto (`🔊 <speech_text>` + `display_text`).
- Roles intercambiables: `front`/`worker` se resuelven por `tony.yaml`; un agente asignado a un rol cuya `role` en `agent.md` no coincide produce una advertencia, no un error.
- Cambios de comportamiento en capacidades existentes: la barrera de ejecución del proxy comprueba la cancelación antes de ejecutar cada tool y el timeout de tarea cubre también la conexión del motor; la confirmación pasa a ser gestionada por el orquestador (una pendiente visible por conversación, `invalid_confirmation` ante id desconocido, resuelto o con tool/args distintos, caducidad → cancelación con motivo `not_confirmed`).
- Sin cambios **BREAKING** para `tony run`: conserva su puerta de confirmación interactiva propia y su comportamiento de la entrega 01.

Fuera de alcance (entregas 03–05): canal web, voz (STT/TTS/VAD), skills (`read_skill`), subagentes (`run_subagent`), `tony mcp add`, hot reload, resumen automático de `preferences.md`, streaming estructurado de la respuesta del `front` en CLI.

## Capabilities

### New Capabilities
- `task-orchestrator`: cola y ciclo de vida de tareas (estados, transiciones atómicas, una raíz activa, límite de cola), flujo de eventos por tarea, cancelación externa, timeout de tarea de extremo a extremo y espera del resultado.
- `front-agent`: ejecución del agente `front` en modo conversación (sesión persistente, prompt con contexto dinámico), tools nativas `delegate`/`remember`/`set_reply_mode`, criterio de delegación y aislamiento del `worker` respecto al canal.
- `user-memory`: memoria de usuario editable (`preferences.md`), ajustes persistentes (`settings.json`) e historial de conversaciones, mensajes y tareas (`conversations.sqlite`).
- `reply-mode`: resolución del modo de respuesta efectivo por mensaje, inyección del estilo correspondiente y contrato de salida `{display_text, speech_text}` del `front`, incluida la frase de espera y el reenvío de progreso al canal.
- `cli-chat`: comando `tony chat` (REPL, comandos locales, confirmaciones, cancelación por `Ctrl+C`, persistencia de turnos, opciones y degradación de modos de voz a texto).

### Modified Capabilities
- `tool-confirmation`: la solicitud de un solo uso pasa a gestionarse por el orquestador: una confirmación pendiente por tarea y una visible por conversación, `confirm()` con id desconocido, ya resuelto o con tool/args distintos devuelve `invalid_confirmation` sin efecto, y rechazo o caducidad cancelan la tarea con motivo `not_confirmed`. La confirmación interactiva de `tony run` no cambia.
- `agent-runner`: el proxy comprueba la cancelación de la tarea antes de ejecutar cada tool (barrera real), el timeout de tarea cubre toda la vida de la sesión del motor (conexión incluida) y la cancelación externa produce `status = "cancelled"` con el motivo recibido.

## Impact

- Código nuevo: `tony/core/orchestrator/` (cola, estados, eventos, confirmación, cancelación, reloj inyectable, factoría del `worker`), `tony/core/memory/` (preferencias, ajustes, SQLite), `tony/core/channels/` (puerto de canal y sesión de chat), `tony/core/runner/` (modo conversación, servidor nativo `tony`, prompt del `front`, modo de respuesta), `tony/apps/cli/` (`chat`, canal CLI, lector de `stdin` no bloqueante), `tests/` (dobles: runner conversacional falso, reloj falso, canal en memoria, SQLite temporal).
- Código modificado: `tony/core/runner/proxy.py` y `tony/core/runner/claude_sdk.py` (barrera de cancelación, alcance del timeout, token de cancelación), `tony/apps/cli/main.py` (comando `chat`), `tests/test_architecture.py` (reglas de dependencia nuevas), `agents/jarvis/agent.md` (prompt con criterio de delegación), `README.md`.
- Dependencias: ninguna nueva; `sqlite3`, `json`, `asyncio`, `threading`, `signal` de la biblioteca estándar. Se mantienen `claude-agent-sdk==0.2.174` (`ClaudeSDKClient` persistente, `create_sdk_mcp_server`, `output_format`) y `typer`.
- Ficheros de datos: `memory/preferences.md`, `memory/settings.json`, `memory/conversations.sqlite` (ya ignorado por `.gitignore`); `memory/` se crea si no existe. Logs JSONL por tarea como en la entrega 01, ahora con los eventos del orquestador.
- Sistemas externos: Claude Code CLI autenticado (igual que en la entrega 01); MCP `filesystem` del `worker` vía `npx` en la sesión de cierre.
- Compatibilidad: `tony run` y sus specs se conservan; los contratos `TaskRequest`/`TaskResult`/evento JSONL no cambian (se añaden tipos de evento, no se altera el contrato).
