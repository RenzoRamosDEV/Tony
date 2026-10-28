# Tony — Spec v1

Oct 27, 2026 · @Renzo

Tony es un asistente personal local con dos agentes: Jarvis (te habla, por voz o texto, según elijas) y Viernes (ejecuta todo por debajo con MCPs, skills y subagentes). Todo lo configurable es un archivo dentro de la carpeta del agente. Esta pestaña es la spec cerrada; la pestaña «Notas de trabajo» guarda el razonamiento, diagramas y alternativas.

## 1. Objetivo y alcance

**Objetivo.** Hablar o escribir a Jarvis desde la CLI o la web, que Viernes resuelva la tarea usando cualquier MCP que yo haya añadido en un json, y que Jarvis me responda por voz o por texto según el modo que yo elija.

**Dentro del alcance v1**

- Dos agentes con roles fijos: `front` (Jarvis) y `worker` (Viernes), intercambiables por config.
- Canales: CLI y web (chat + voz).
- MCPs por `tool.json` (stdio y HTTP), skills `SKILL.md`, subagentes como carpetas.
- Modo de respuesta elegible: `auto`, `voice`, `text`, `both`.
- Memoria de usuario en ficheros.
- Confirmación para tools marcadas como peligrosas.

**Fuera del alcance v1** (fase 5+): proactividad por scheduler, Telegram, perfiles por contexto, modo offline, wake word, barge-in.

**Usuario**: uno (yo), en mi portátil. No hay multiusuario ni despliegue en servidor en v1.

## 2. Requisitos funcionales

| ID | Requisito | Criterio de aceptación |
| --- | --- | --- |
| RF-01 | Jarvis es el único agente que habla con el usuario | Ningún mensaje de Viernes llega al usuario sin pasar por Jarvis |
| RF-02 | Jarvis decide si responde solo o delega en Viernes | «¿Qué hora es?» no genera tarea; «lista los PRs abiertos» sí |
| RF-03 | Viernes recibe una tarea estructurada y devuelve un resultado estructurado | JSON `{objetivo, contexto, restricciones}` → `{resumen, datos, pasos, errores}` |
| RF-04 | Conectar un MCP es añadir una entrada en `tool/tool.json` | Añadir el MCP de filesystem y usarlo sin tocar código Python |
| RF-05 | Soporte stdio (`command`+`args`) y HTTP (`url`) | Un MCP local y uno remoto funcionan a la vez |
| RF-06 | `allow` filtra qué tools del MCP ve el agente | Con `allow: ["fs.read_file"]` el agente no ve `fs.write_file` |
| RF-07 | Un MCP caído no bloquea el arranque | Ruta inválida → log de error, el resto de tools disponibles |
| RF-08 | Skills en `skills/<nombre>/SKILL.md`, cargadas bajo demanda | El prompt base no incluye el cuerpo de las skills; se inyecta al activarse |
| RF-09 | Subagentes como carpetas con la misma estructura | `run_subagent("investigador", tarea)` ejecuta `subagents/investigador/` |
| RF-10 | Entrada por texto (CLI y web) y por voz (web) | Las tres entradas llegan a Jarvis como texto idéntico |
| RF-11 | Modo de respuesta elegible: `auto`, `voice`, `text`, `both` | Cambiar el modo cambia la salida en el siguiente mensaje |
| RF-12 | El modo se cambia por botón, por frase a Jarvis o por prefijo `/v` `/t` | Las tres vías funcionan y la persistente se guarda en `memory/preferences.md` |
| RF-13 | En voz, contenido largo o código se resume en audio y se muestra completo en pantalla | Una tabla nunca se lee en voz alta |
| RF-14 | Respuesta en streaming y TTS por frases | El audio empieza antes de que termine la respuesta completa |
| RF-15 | Avisos de progreso mientras Viernes trabaja | Tarea > 3 s → Jarvis dice/escribe que está en ello |
| RF-16 | Tools con `confirm: true` requieren un sí explícito | Sin confirmación la tool no se ejecuta y la tarea queda pausada |
| RF-17 | Memoria de usuario editable a mano | «Recuerda que X» escribe una línea en `memory/preferences.md`; editarla a mano se refleja al reiniciar |
| RF-18 | Front y worker intercambiables por config | Cambiar `front: viernes` en `tony.yaml` hace que Viernes hable |
| RF-19 | CLI de gestión: `tony chat`, `tony mcp add/list`, `tony agents` | Cada comando documentado en `--help` |
| RF-20 | Panel de debug en la web | Muestra tool calls, subagentes y tokens de la tarea actual |

## 3. Arquitectura

Canal → Jarvis → Orquestador → Viernes → Tools, y vuelta. Cinco componentes, cada uno con una sola responsabilidad.

| Componente | Responsabilidad | Entrada | Salida |
| --- | --- | --- | --- |
| Canales (`core/channels`) | Recibir texto o audio, devolver texto o audio en streaming | mensaje del usuario | respuesta de Jarvis |
| Jarvis (`agents/jarvis`) | Conversar, recordar, decidir si delega, redactar la respuesta final en el estilo del modo activo | texto + historial + memoria | respuesta o `delegate(tarea)` |
| Orquestador (`core/orchestrator`) | Cola de tareas, eventos de progreso, pausa por confirmación, cancelación | tarea | eventos + resultado |
| Viernes (`agents/viernes`) | Planificar y ejecutar con tools; lanzar subagentes | tarea estructurada | resultado estructurado |
| Loader + MCP manager (`core/loader`, `core/mcp`) | Leer carpetas de agentes, arrancar MCPs, exponer tools filtradas | sistema de archivos | agentes listos |

Reglas duras:

1. Jarvis tiene una sola tool especial, `delegate`; no tiene acceso a MCPs salvo que su `tool.json` lo diga.
2. Viernes no tiene acceso al canal; no puede escribir al usuario.
3. El orquestador es el único que conoce a los dos agentes; ninguno conoce al otro por nombre, solo por rol.
4. Todo lo que pasa entre componentes es JSON serializable, para poder registrarlo y repetirlo en evals.

El diagrama del flujo y el detalle de cada agente están en «Notas de trabajo».

## 4. Repo y formato de archivos

```
tony/
├── agents/
│   ├── jarvis/
│   │   ├── agent.md
│   │   ├── skills/<nombre>/SKILL.md
│   │   ├── subagents/<nombre>/   (misma estructura que un agente)
│   │   └── tool/tool.json
│   └── viernes/                  (misma estructura)
├── core/        loader · mcp · orchestrator · channels · voice
├── apps/        cli · web
├── config/      tony.yaml · .env
├── memory/      preferences.md · conversations.sqlite
└── evals/       tareas.yaml · conversaciones.yaml
```

**`agent.md`** — frontmatter YAML + prompt del sistema en markdown.

```yaml
---
name: jarvis
role: front            # front | worker
model: claude-haiku    # alias definido en tony.yaml
persona:
  address: señor
  language: es
style:
  voice: "Frases cortas, sin markdown, números redondeados."
  text: "Markdown, detalle completo, tablas si ayudan."
max_steps: 20
---
Eres Jarvis, el asistente personal de Renzo...
```

**`tool/tool.json`** — mismo esquema que Claude Desktop / Claude Code, más tres campos propios.

```json
{
  "mcpServers": {
    "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/renzo"] },
    "notion":     { "url": "https://mcp.notion.com/mcp" }
  },
  "native": ["run_subagent", "read_skill", "remember"],
  "allow":  ["filesystem.*", "notion.search"],
  "confirm": ["filesystem.write_file", "filesystem.delete"]
}
```

- `command`+`args` → stdio; `url` → HTTP streamable. `${VAR}` se lee de `.env`.
- `native`: tools del core. `allow`: lista blanca (sin ella, todas). `confirm`: tools que piden confirmación.
- Subagente con `tool.json` vacío → hereda las tools del padre.

**`skills/<nombre>/SKILL.md`** — formato de Claude Code: frontmatter `name`, `description`, opcional `trigger: ["frase 1", "frase 2"]` para protocolos por voz; cuerpo con las instrucciones.

**`config/tony.yaml`**

```yaml
front: jarvis
worker: viernes
reply_mode: auto          # auto | voice | text | both
models:
  claude-haiku: anthropic/claude-haiku-4-5
  claude-sonnet: anthropic/claude-sonnet-4-5
voice:
  stt: faster-whisper/small
  tts: kokoro/es-f1
  vad: silero
channels: [cli, web]
web:
  port: 8787
```

**`memory/preferences.md`** — líneas `- [YYYY-MM-DD] texto` que Jarvis añade con `remember` y tú puedes editar. Se inyecta entero en el prompt de Jarvis (límite 200 líneas; después, resumir).

## 5. Flujos clave

**F1 · Petición normal (voz, modo `auto`)**

1. El navegador captura audio; Silero VAD detecta el final de la frase y envía el audio por WebSocket.
2. `core/voice` transcribe con faster-whisper → texto.
3. Jarvis recibe texto + historial + `preferences.md` + `style.voice`.
4. Jarvis llama a `delegate({objetivo, contexto, restricciones})`.
5. El orquestador encola la tarea y emite `progress` cada vez que Viernes llama a una tool.
6. A los 3 s sin resultado, Jarvis emite una frase de espera («Dame un momento, señor») que se sintetiza y reproduce.
7. Viernes devuelve `{resumen, datos, pasos, errores}`.
8. Jarvis redacta la respuesta en estilo voz; el core la trocea por frases, cada frase va a Kokoro y se reproduce mientras llega la siguiente.
9. La transcripción completa se muestra en pantalla; si `datos` tiene tabla o código, se muestra completo y Jarvis solo lo resume en audio.

**F2 · Cambiar el modo de respuesta**

- Botón del front → `PATCH /settings {reply_mode}` → se guarda en `preferences.md`.
- Frase a Jarvis («respóndeme por escrito») → Jarvis llama a `set_reply_mode("text")` → mismo efecto + confirma en una frase.
- Prefijo `/v` o `/t` en un mensaje → solo esa respuesta; el modo guardado no cambia.
- El core inyecta `style.voice` o `style.text` según el modo efectivo de cada respuesta.

**F3 · Tool con confirmación**

1. Viernes intenta `filesystem.delete`; está en `confirm` → el orquestador pausa la tarea y emite `needs_confirmation {tool, args}`.
2. Jarvis pregunta en el modo activo: «Voy a borrar `notas.md`. ¿Confirmo, señor?».
3. «Sí» → `confirm(task_id)` y Viernes continúa. «No» o 60 s sin respuesta → tarea cancelada, Jarvis lo dice.

**F4 · Añadir un MCP**

1. `tony mcp add github https://api.githubcopilot.com/mcp --agent viernes` escribe la entrada en `agents/viernes/tool/tool.json`.
2. El loader detecta el cambio (watchfiles), arranca el servidor, lista sus tools y las registra.
3. `tony mcp list` muestra `github: 12 tools (allow: todas)`. Sin reinicio.

**F5 · Subagente**

1. Viernes llama a `run_subagent("investigador", tarea)`.
2. El loader construye el subagente desde `subagents/investigador/` (su `agent.md`, skills y `tool.json`; si está vacío hereda las tools).
3. El subagente corre con su propio historial y devuelve un resultado estructurado a Viernes, que lo integra. El panel de debug lo muestra como hijo de la tarea.

## 6. Stack cerrado

Decidido, sin alternativas; si algo falla en la fase 1 se revisa ahí.

| Capa | Elección |
| --- | --- |
| Lenguaje / core | Python 3.12, `uv` para dependencias |
| Loop de agente | Claude Agent SDK (Python): MCP, subagentes y skills nativos |
| Modelos | Jarvis: Claude Haiku · Viernes y subagentes: Claude Sonnet |
| MCP | SDK oficial `mcp`, transportes stdio y HTTP streamable |
| API | FastAPI + WebSocket (streaming de tokens, audio y eventos) |
| Web | React + Vite + TypeScript; audio con Web Audio API |
| STT | faster-whisper, modelo `small`, en CPU |
| TTS | Kokoro, voz española |
| VAD | Silero VAD |
| Config | YAML + `.env` con pydantic-settings; hot reload con `watchfiles` |
| Memoria | `preferences.md` + SQLite (`conversations.sqlite`) |
| Evals | pytest + YAML de tareas; juez con Claude para las de conversación |
| Observabilidad | Log JSONL por tarea en `logs/`, compatible con AgentBoard |

## 7. Roadmap y criterios de aceptación

| Fase | Entregable | Se cierra cuando |
| --- | --- | --- |
| 1 · Core + Viernes | Loader, MCP manager, `tony run viernes "tarea"` | Viernes resuelve una tarea usando 2 tools de un MCP real desde la CLI |
| 2 · Jarvis + chat | Orquestador, `delegate`, memoria, FastAPI, web con panel de debug | Uso el chat web a diario durante una semana sin tocar código |
| 3 · Skills + subagentes + CLI | `read_skill`, `run_subagent`, `tony mcp add/list`, evals de tareas | Añado un MCP y una skill nuevos sin editar Python; 10 evals en verde |
| 4 · Voz y modos | VAD + STT + TTS por frases, modos `auto/voice/text/both`, confirmación | Ida y vuelta por voz < 2 s en tareas sin tools; cambio de modo por botón, voz y prefijo |
| 5 · Jarvis de verdad | Scheduler proactivo, hot reload, protocolos por frase, HUD completo | Briefing de las 8:00 funciona 5 días seguidos |
| 6 · Fuera de casa | Telegram, perfiles por contexto, modo offline | Le hablo desde el móvil con nota de voz y me responde |

Primeras tareas (fase 1):

- [ ] Crear el repo con la estructura de carpetas y `agents/viernes/` mínimo
- [ ] Loader: leer `agent.md` y `tool/tool.json`, validar con pydantic
- [ ] MCP manager: arrancar filesystem por stdio, listar tools, aplicar `allow`
- [ ] `tony run viernes "lista los .md de ~/notas y resume el más reciente"`
- [ ] Log JSONL de la tarea

## 8. Requisitos no funcionales

- **Latencia**: texto, primer token < 1 s; voz, primera frase de audio < 2 s sin tools.
- **Robustez**: un MCP o subagente que falla nunca tumba el proceso; timeout de 20 s por tool, 5 min por tarea.
- **Seguridad**: claves solo en `.env`; tools destructivas en `confirm`; Viernes solo accede a rutas listadas en `args` del MCP.
- **Coste**: Jarvis en Haiku; log de tokens por tarea; alerta en el panel si una tarea pasa de 50 k tokens.
- **Portabilidad**: corre en Linux (Bazzite) con `uv run tony`; nada requiere Docker.
- **Trazabilidad**: cada tarea se puede reproducir desde su log JSONL para depurar o convertirla en eval.
