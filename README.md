# Tony

Asistente personal local con dos agentes: **Jarvis** (`front`, habla contigo) y
**Viernes** (`worker`, ejecuta tareas con MCPs). Incluye el núcleo (carga de agentes
desde ficheros, gestor de MCPs, ejecución sobre Claude Agent SDK con resultado
estructurado y log JSONL por tarea), el orquestador de tareas, la memoria de usuario y
la conversación por terminal con `tony chat`.

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
uv run pytest -q        # suite sin red ni modelo real (< 60 s)
uv run ruff check .
```
