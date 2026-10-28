# Tony

Asistente personal local con dos agentes: **Jarvis** (`front`, habla contigo) y
**Viernes** (`worker`, ejecuta tareas con MCPs). Incluye el núcleo (carga de agentes
desde ficheros, gestor de MCPs, ejecución sobre Claude Agent SDK con resultado
estructurado y log JSONL por tarea), el orquestador de tareas, la memoria de usuario,
la conversación por terminal con `tony chat` y el chat web con panel de debug con `tony web`.

## Requisitos

- Python 3.12 gestionado con [uv](https://docs.astral.sh/uv/).
- Node.js con `npx` (para el MCP de filesystem).
- [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) instalado y autenticado
  (`claude` en el PATH). Tony usa esa autenticación; no necesitas `ANTHROPIC_API_KEY`.

## Instalación

```bash
uv sync
uv run tony --help
```

## Primer uso con el MCP de filesystem

Viernes viene configurado con el MCP `@modelcontextprotocol/server-filesystem` sobre
`~/notas`. Crea la carpeta si no existe y precarga el servidor una vez (la primera descarga
de `npx` puede superar el timeout de conexión de 10 s; el comando arranca el servidor y
termina al cerrar la entrada estándar):

```bash
mkdir -p ~/notas
npx -y @modelcontextprotocol/server-filesystem@2026.8.31 ~/notas < /dev/null
```

Se fija la versión `2026.8.31` porque `2025.8.21` publica tools con `inputSchema` vacío
(sin `type: object`), que el cliente MCP rechaza y deja a Viernes sin tools.

Después ejecuta una tarea:

```bash
uv run tony run viernes "lista los .md de ~/notas y resume el más reciente"
uv run tony run viernes "lista los .md de ~/notas" --json
uv run tony version
```

Opciones de `tony run`: `--json` (imprime el `TaskResult` como JSON), `--agents-dir`
(directorio de agentes, por defecto `agents/`) y `--config` (por defecto
`config/tony.yaml`). Códigos de salida: `0` si el estado es `ok` o `partial`, `1` si es
`error`, `cancelled` o `timeout`, `2` si el agente no existe, no es `worker` o no carga.

## Conversar con Jarvis: `tony chat`

```bash
uv run tony chat            # continúa la última conversación de la terminal
uv run tony chat --new      # empieza una conversación nueva
uv run tony chat --help
```

Opciones: `--config` (por defecto `config/tony.yaml`), `--agents-dir` (por defecto
`agents/`) y `--new`. El prompt es `tú> `; las respuestas van a `stdout` y los avisos,
el progreso y las preguntas a `stderr`. Jarvis responde por sí mismo a la conversación,
las preguntas generales, la hora y tus preferencias, y delega en Viernes cuando hacen
falta ficheros, datos externos o herramientas. Mientras una tarea delegada corre verás
su progreso como líneas `· <tool>` y, si tarda más de 3 s, la frase de espera de Jarvis.

Comandos locales (no llegan a Jarvis):

| Comando | Efecto |
|---|---|
| `/mode` | Muestra el modo de respuesta persistido o, si no hay, el de `tony.yaml`. |
| `/mode auto\|voice\|text\|both` | Guarda el modo en `memory/settings.json`. |
| `/memoria` | Imprime `memory/preferences.md` completo. |
| `/cancel` | Cancela la tarea activa. |
| `/salir` | Termina (también `Ctrl+D`). |

Prefijos por mensaje: `/v texto`, `/t texto` y `/b texto` fuerzan `voice`, `text` o
`both` solo para ese mensaje, sin tocar los ajustes. La precedencia es prefijo >
`settings.json` > `tony.yaml`; `auto` se resuelve a `text` cuando escribes (a `voice`
cuando la entrada es audio, en entregas posteriores). En la terminal los modos de voz se
degradan a texto: primero `🔊 <resumen hablado>` y después la respuesta completa.

Confirmaciones: cuando Viernes necesita una tool de `confirm` (o marcada como
destructiva), verás `Viernes quiere ejecutar <tool> {...}. ¿Confirmas? [s/N]`. Solo `s`,
`si` o `sí` aprueban; Intro vacío o cualquier otra respuesta rechaza y la tarea termina
`cancelled`. Sin respuesta en `limits.confirm_timeout_s` (60 s) la tarea se cancela por
falta de confirmación y la sesión sigue.

`Ctrl+C` durante una tarea delegada la cancela y vuelve al prompt; un segundo `Ctrl+C`
(o `Ctrl+C` sin tarea en curso) cierra la sesión ordenadamente.

## Chat web: `tony web`

La misma sesión de chat de la terminal, servida en el navegador con streaming de eventos, botones
para confirmar tools, selector del modo de respuesta y un panel de debug (RF-20).

```bash
uv sync --extra web                                   # fastapi, uvicorn y websockets
cd tony/apps/web/frontend && npm install && npm run build && cd -
uv run tony web --open                                # http://127.0.0.1:8787/
uv run tony web --help
```

Opciones: `--port` y `--host` (por defecto `web.port` 8787 y `web.host` 127.0.0.1 de
`config/tony.yaml`), `--open` (abre el navegador al arrancar), `--allow-remote` (obligatorio para un
`--host` fuera de loopback; el servidor avisa de que no hay autenticación ni HTTPS), `--config` y
`--agents-dir` como en `tony chat`. Sin el extra, `tony web` termina con código 2 indicando
`uv sync --extra web`; sin el frontend compilado, `GET /` muestra una página con el comando de
`build`. `Ctrl+C` cierra los sockets (código 1001), cancela las tareas activas y para el servidor.

Política de `Origin`: toda petición mutante (`POST`, `PATCH`, `PUT`, `DELETE`) y toda conexión al
WebSocket deben llevar `Origin: http://<host>:<port>` (`localhost` y `127.0.0.1` se consideran
equivalentes); si no, `403 {"error": "forbidden_origin"}`. Los `GET` sin `Origin` (por ejemplo
`curl`) se aceptan. Para desarrollar el frontend, `npm run dev` levanta Vite en `:5173` con un
proxy a `127.0.0.1:8787` que reescribe el `Origin` solo en ese caso.

Streaming en v1: el motor del `front` devuelve la respuesta estructurada completa al final del turno
(sin fragmentos parciales), así que el navegador recibe `user.accepted` al instante, la burbuja de
espera y los eventos de tools, y un único `assistant.final`; el tipo `assistant.delta` forma parte del
protocolo y la UI lo soporta para cuando el motor entregue fragmentos.

Panel de debug (plegable, estado recordado en el navegador): árbol de la tarea raíz y sus
subagentes con estado, tool calls con argumentos redactados, duración y error, tokens y coste por
tarea y acumulados de la conversación, alerta "Tarea > 50 k tokens" cuando una tarea supera
`limits.token_alert`, ruta del JSONL de la tarea con botón de copia, eventos
`config.reloaded`/`config.reload_failed` y "Copiar JSON" con el árbol completo.

API HTTP (JSON; errores siempre `{"error", "detail"}`):

| Método y ruta | Respuesta |
|---|---|
| `GET /api/health` | `{status, version, front, worker, mcp: [{name, state, tool_count}]}` |
| `GET /api/settings` | `{reply_mode, reply_mode_source: "settings" \| "yaml"}` |
| `PATCH /api/settings` `{reply_mode}` | persiste en `memory/settings.json`; `422` si no es válido |
| `POST /api/tasks/{id}/confirm` `{confirmation_id, approved}` | `{ok: true}` o `409 invalid_confirmation` |
| `POST /api/tasks/{id}/cancel` | `{ok: true}`; `404 unknown_task` |
| `GET /api/conversations` | las 20 más recientes `{id, channel, created_at}` |
| `GET /api/conversations/{id}/messages` | `{id, role, content, reply_mode, created_at}`; `404 unknown_conversation` |
| `GET /api/memory` | `{content, lines}` de `memory/preferences.md` |

WebSocket `/ws/chat` (protocolo `v: 1`, sobre `{v, type, seq, conversation_id, message_id?,
task_id?, payload}`): el cliente envía `hello`, `user.text`, `confirm`, `cancel` y `set_mode`; el
servidor responde `hello.ok`, `user.accepted`, `assistant.delta`, `assistant.wait`,
`assistant.final`, `usage`, los eventos `task.*`/`tool.*`/`subtask.*`, `config.*` y `error`.
Cada conversación numera sus mensajes con `seq`; al reconectar, `hello {conversation_id,
last_seq}` reenvía solo los posteriores (o `resync: true` si son demasiado antiguos). Mensajes de
más de 32 KiB se rechazan con cierre `1009`; los tipos `audio.*` quedan reservados para la voz.

## Memoria

Tony crea `memory/` al primer uso (está ignorada por git):

- `memory/preferences.md`: una preferencia por línea con el formato
  `- [YYYY-MM-DD] texto`. Jarvis la amplía con la tool `remember` y tú puedes editarla a
  mano; se relee en cada turno y se inyectan como máximo las últimas
  `limits.memory_max_lines` (200) líneas, sin resumir ni borrar nada del fichero.
- `memory/settings.json`: ajustes persistentes, por ejemplo `{"reply_mode": "text"}`.
  Un fichero ausente o inválido equivale a ajustes vacíos (con un aviso en el log).
- `memory/conversations.sqlite`: conversaciones, mensajes (con su modo de respuesta) y
  tareas delegadas con estado, tokens y coste.

## Configuración

`config/tony.yaml` es opcional; cada campo ausente toma su valor por defecto (ver los
comentarios del fichero de ejemplo). `config/.env` (copia `config/.env.example`) guarda los
secretos que tus MCPs necesiten y nunca se versiona.

Los roles se asignan por configuración: `front: jarvis` y `worker: viernes` por defecto.
Puedes intercambiarlos (`front: viernes`, `worker: jarvis`); si el `role` declarado en
`agent.md` no coincide con el rol asignado, `tony chat` avisa por `stderr` y continúa.

## Definir un agente

Cada agente es una carpeta en `agents/<nombre>/`:

`agent.md` — frontmatter YAML + system prompt:

```markdown
---
name: viernes
role: worker            # front | worker
model: claude-sonnet    # alias definido en models de tony.yaml
persona: {address: "", language: es}
style: {voice: "", text: ""}
max_steps: 20           # 1..200
wait_phrase: "Dame un momento."
---
Eres Viernes...
```

`tool/tool.json` — MCPs y políticas:

```json
{
  "mcpServers": {
    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem@2026.8.31", "${HOME}/notas"]},
    "notion": {"url": "https://mcp.notion.com/mcp", "headers": {"Authorization": "Bearer ${NOTION_TOKEN}"}}
  },
  "native": ["delegate", "remember", "set_reply_mode", "read_skill", "run_subagent"],
  "allow": ["filesystem.*", "notion.search"],
  "confirm": ["filesystem.write_file", "filesystem.edit_file", "filesystem.move_file"]
}
```

- Un servidor es stdio si tiene `command` y HTTP si tiene `url` (nunca ambos).
- `${VAR}` se sustituye con el entorno del proceso y `config/.env` (el entorno gana).
- `allow` ausente significa "todas las tools"; `allow: []` no deja ninguna.
- Las tools de `confirm` y las anotadas como destructivas por el MCP piden confirmación
  `[s/N]` en la terminal (60 s); si la rechazas, la tarea termina con `cancelled`.

## Skills

Una skill es conocimiento que el agente lee bajo demanda. Vive en
`agents/<agente>/skills/<nombre>/SKILL.md`:

```markdown
---
name: resumen-web                     # igual que la carpeta
description: Resume una página web en 5 viñetas con fuente y fecha.   # ≤ 200 caracteres
trigger: ["resume esta web", "resúmeme la página", "resume https"]    # opcional
---
1. Descarga la página con `fetch.fetch`...
```

- El system prompt del `front` y del `worker` solo incluye el índice `Skills disponibles:`
  (nombre y descripción); el cuerpo llega por la tool nativa `read_skill(nombre)` o se inyecta
  automáticamente como bloque `<skill name="…">…</skill>` cuando el texto del usuario (o el
  `objetivo`/`contexto` de la tarea) contiene una frase de `trigger`, sin distinguir mayúsculas
  ni acentos. Cada skill activada se inyecta una sola vez por turno.
- Una skill inválida (nombre distinto de la carpeta, `description` ausente o demasiado larga,
  frontmatter ausente) se registra como error (`tony agents`, `tony doctor`) y no bloquea al agente.
- Viernes incluye la skill `resumen-web`; `read_skill` se declara en `native` de `tool.json`.

## Subagentes

Un `worker` puede descomponer una tarea con la tool nativa `run_subagent(nombre, objetivo,
contexto, restricciones)`, que ejecuta `agents/<agente>/subagents/<nombre>/` (misma estructura
que un agente: `agent.md`, `skills/`, `tool/tool.json`) como subtarea del orquestador, con sesión
e historial propios, y devuelve su `TaskResult`. Viernes incluye el subagente `investigador`.

Permisos del hijo = intersección con los del padre:

| `allow` del padre | `tool.json` del hijo                        | catálogo efectivo del hijo   |
|-------------------|---------------------------------------------|------------------------------|
| `["fs.*"]`        | ausente o vacío                             | `fs.read_file`, `fs.write_file` (el catálogo exacto del padre) |
| `["fs.*"]`        | `allow: ["fs.read_file", "notion.*"]`       | `fs.read_file`               |
| ausente (todas)   | `allow: ["fs.read_file"]`                   | `fs.read_file`               |

- `confirm` del padre se hereda siempre; el hijo puede añadir entradas.
- El hijo puede declarar servidores MCP nuevos (se conectan solo para esa subtarea y pasan por
  el `allow` del padre) salvo que el padre sea a su vez un subagente. Un nombre repetido usa la
  definición del padre.
- Límites: profundidad máxima 1 (un subagente no carga `subagents/` ni expone `run_subagent`),
  máximo 2 subagentes concurrentes por tarea (el tercero espera), fecha límite compartida con la
  tarea padre (`task_timeout_s` desde que el padre entró en `running`) y la misma puerta de
  confirmación: la pregunta `[s/N]` del hijo aparece en la conversación y un rechazo cancela solo
  la subtarea.
- Los eventos del hijo llevan `task_id` propio y `parent_id`; el padre recibe
  `subtask.started {task_id, agent}` y `subtask.finished {task_id, status}`, y su log registra
  `tool.call`/`tool.result` de `tony.run_subagent`.
- En `tony run` no hay orquestador: `run_subagent` devuelve un `TaskResult` de error y se avisa
  al arrancar. Los subagentes funcionan en `tony chat` (y en el servidor web).

## Gestionar servidores MCP: `tony mcp`

```bash
uv run tony mcp add fetch -- uvx mcp-server-fetch --agent viernes          # stdio
uv run tony mcp add notion https://mcp.notion.com/mcp --agent viernes \
    --header "Authorization=Bearer \${NOTION_TOKEN}" --allow notion.search  # HTTP
uv run tony mcp add x -- cmd --agent viernes --env TOKEN=\${TOKEN}         # entorno del servidor
uv run tony mcp remove fetch --agent viernes
uv run tony mcp list [--agent viernes] [--no-connect]
```

`add` edita `agents/<agente>/tool/tool.json` de forma atómica (indentación 2, el resto del fichero
se conserva; se crea si no existe), conecta al servidor con `limits.mcp_connect_timeout_s` y
muestra `<nombre>: N tools (allow: todas|<patrones>)`. Si la conexión falla, la entrada queda
escrita igualmente con un aviso (código 0). Un nombre existente falla salvo con `--force`. Las
opciones se reconocen aunque vayan después de `--`; si el servidor tiene una opción homónima
(por ejemplo `--env`), pon la de Tony antes de `--`. `list` muestra
`agente | servidor | transporte | estado | tools | allow | confirm` (subagentes como
`viernes/investigador`); con `--no-connect` no arranca ningún proceso.

## Inventario de agentes: `tony agents`

```bash
uv run tony agents                      # nombre | rol | modelo | skills | MCP | nativas
uv run tony agents show viernes         # AgentSpec resuelto en YAML (secretos como ***)
uv run tony agents show viernes/investigador
```

Un agente, subagente o skill que no carga aparece con `✗` y el motivo sin impedir el listado.

## Diagnóstico: `tony doctor` y `tony config validate`

```bash
uv run tony doctor              # incluye una petición mínima a claude-haiku y conecta a cada MCP
uv run tony doctor --offline    # sin la petición al modelo
uv run tony config validate     # sin red ni procesos (lo mismo que usa la recarga en caliente)
```

Cada comprobación es una línea `✓`, `✗` (con una sugerencia debajo) o `·` (informativa): Python
3.12, CLI `claude`, modelo, `config/tony.yaml`, `config/.env` (debe existir con permisos `600`),
cada agente, subagente y skill (incluidas las variables `${VAR}`), `node`/`npx` si algún MCP los
usa, extras de voz y `espeak-ng` (solo informan), conexión a cada MCP y patrones de
`allow`/`confirm` que no coinciden con ninguna tool. El código de salida es `1` si hay algún `✗`.

## Recarga en caliente de `tool.json`

Mientras `tony chat` está en marcha, Tony observa `agents/**/tool/tool.json`. Al guardar el del
`worker` (o el de uno de sus subagentes) se valida la configuración como `tony config validate`;
si es válida arranca una nueva generación de servidores MCP para las tareas nuevas (las tareas en
curso conservan la anterior, que se cierra cuando ninguna la usa) y se avisa en la terminal con el
evento `config.reloaded {agent, servers}`. Si no es válida (JSON mal formado, `${VAR}` sin
definir…) se conserva la última configuración válida y se emite `config.reload_failed {agent,
error}`. `agent.md`, las skills y `tony.yaml` siguen exigiendo reiniciar; un cambio en la carpeta
del `front` solo produce un aviso. `tony run` no observa nada.

## Logs

Cada tarea escribe `logs/<YYYYMMDD>/<task_id>.jsonl` con un evento por línea
(`mcp.status`, `task.started`, `tool.call`, `tool.result`, `assistant.text`, `task.finished`). La ruta
aparece en la última línea de la salida de `tony run`. Las tareas delegadas desde
`tony chat` añaden los eventos del orquestador (`task.queued`, `task.running`,
`task.progress`, `task.needs_confirmation`, `task.confirmed`, `task.cancelled` y
`task.result` como última línea) y cada conversación escribe además
`logs/<YYYYMMDD>/chat-<conversation_id>.jsonl` con el texto de Jarvis.

Antes de escribir, Tony redacta con `***` los valores de las claves `authorization`,
`api_key` y `token` (sin distinguir mayúsculas) y cualquier valor de `config/.env` de
8 o más caracteres; los valores más cortos (por ejemplo un puerto) no se redactan.

## Desarrollo

```bash
uv run pytest -q        # suite sin red ni modelo real (< 60 s); tests/apps/web/ requiere el extra web
uv run ruff check .
cd tony/apps/web/frontend && npm test && npm run lint && npm run build   # frontend (Vitest + tsc)
```

### Evals

`evals/tareas.yaml` (6 tareas del worker sobre un MCP de ficheros falso) y
`evals/conversaciones.yaml` (4 conversaciones del front) describen cada eval y sus expectativas
(`status`, `tools_called_any`, `tools_called_all`, `resumen_contains`; `delegates`,
`reply_contains`, `judge`). No forman parte de `uv run pytest`:

```bash
uv run pytest evals/ -m evals                 # reproduce evals/fixtures/<id>.jsonl, sin red
TONY_EVALS=1 uv run pytest evals/ -m evals    # modelo real; graba evals/runs/<fecha>/<id>.jsonl
uv run tony replay logs/<fecha>/<task_id>.jsonl                  # eventos legibles, sin ejecutar tools
uv run tony replay evals/runs/<fecha>/fs-list-md.jsonl --to-eval fs-list-md [--force]
```

Con `TONY_EVALS=1` el juez (`claude-haiku`) evalúa el criterio `judge` de cada turno. `--to-eval`
escribe `evals/fixtures/<id>.jsonl` e imprime la entrada YAML con el `status` y las tools
observadas; los fixtures de conversación son el propio run copiado. `evals/runs/` está ignorado
por git.
