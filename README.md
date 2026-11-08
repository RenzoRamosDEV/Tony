<div align="center">

# Tony

**Asistente personal local, con tres agentes de rol fijo y un guardián de permisos.**

Jarvis conversa, Viernes ejecuta, Edith decide qué se puede hacer sin preguntar y qué necesita tu
confirmación. Todo corre en tu máquina: el modelo es la única pieza remota (vía el SDK de Claude).

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-Qt%206-41CD52?logo=qt&logoColor=white)
![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=white)
![Claude](https://img.shields.io/badge/Claude-Agent%20SDK-D97757?logo=anthropic&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-servidores-000000)
![Flatpak](https://img.shields.io/badge/Flatpak-KDE%206.8-4A86CF?logo=flatpak&logoColor=white)

</div>

---

## Qué es

Tony es un asistente personal que vive en tu escritorio (o en la terminal). Le hablas o le
escribes, y él hace cosas: lee y escribe tus notas, consulta tu calendario, busca en tu Drive,
gestiona tu correo, usa tu vault de Obsidian — lo que le conectes. Todo con un principio simple:
**ninguna acción real ocurre sin que una política explícita la permita**, y las que importan te
las pregunta antes de hacerlas.

No hay un único modelo haciendo de todo. Hay **tres agentes con un papel fijo cada uno**, y un
cuarto rol —el guardián— que no es un agente que decide con criterio propio, sino una política
determinista (YAML, sin modelo) que se evalúa antes de cada acción.

| Agente | Rol | Qué hace | Color |
|---|---|---|---|
| 🗣️ **Jarvis** | `front` | Habla contigo, entiende lo que pides y se lo encarga a Viernes | 🔵 `#2F6FED` |
| 🛠️ **Viernes** | `worker` | Ejecuta la tarea: usa tools, servidores MCP, skills y subagentes | 🟢 `#2E9E5B` |
| 🛡️ **Edith** | `guard` | Antes de cada tool, decide `allow` / `confirm` / `deny` según la política | 🟡 `#E0A100` |

---

## Cómo está montado

```
tú escribes o hablas
        │
        ▼
 ┌─────────────┐
 │   Jarvis    │
 │   (front)   │
 └─────────────┘
        │  delegate(objetivo, contexto, restricciones)
        ▼
 ┌─────────────┐
 │   Viernes   │
 │  (worker)   │
 └─────────────┘
        │  antes de cada llamada a una tool
        ▼
 ┌─────────────┐
 │    Edith    │
 │   (guard)   │
 └─────────────┘
        │  decide con policy.yaml — allow / confirm / deny (sin modelo)
        ▼
 ┌──────────────────────────────────────────────────────┐
 │                    servidores MCP                     │
 │  filesystem · gmail · gdrive · calendar · obsidian…   │
 └──────────────────────────────────────────────────────┘
```

- **Jarvis** nunca toca una tool directamente: todo lo que requiere actuar en el mundo real pasa
  por `delegate` a Viernes.
- **Viernes** recibe una tarea estructurada (`objetivo`, `contexto`, `restricciones`) y la resuelve
  llamando a tools: de un servidor MCP (`<servidor>.<tool>`), nativas (`tony.<nombre>`) o, si la
  tarea lo pide, un subagente suyo.
- **Edith** no es un paso opcional: **toda** llamada a tool de Viernes pasa primero por su
  política, determinista y sin modelo detrás (el modelo de Edith solo redacta la *pregunta* cuando
  hace falta confirmar — nunca decide el veredicto).

---

## El flujo de una tarea

```
Tú: "Borra el archivo viejo de notas"
        │
        ▼
 ┌─────────────┐
 │   Jarvis    │
 └─────────────┘
        │  delegate(objetivo, contexto, restricciones)
        ▼
 ┌─────────────┐
 │   Viernes   │
 └─────────────┘
        │  filesystem.delete_file(...)
        ▼
 ┌─────────────┐
 │    Edith    │
 └─────────────┘
        │  evalúa policy.yaml: gana la primera regla que encaja
        ▼
 ┌──────────────────────────────┐
 │    allow / confirm / deny    │
 │      (ver tabla debajo)      │
 └──────────────────────────────┘
                 │
                 ▼
 ┌───────────────────────────────────┐
 │ {resumen, datos, pasos, errores}  │
 └───────────────────────────────────┘
                   │
                   ▼
 ┌────────────────────────┐
 │  Jarvis te lo explica  │
 └────────────────────────┘
```

| Veredicto | Qué pasa |
|---|---|
| `allow` | la tool se ejecuta directamente |
| `confirm` | Edith pregunta «Acción: borrar X. Regla: r. ¿Autoriza?»; si dices que sí, se ejecuta — si no, o se agota el tiempo, no |
| `deny` | no se ejecuta; Viernes recibe `{"error": "blocked_by_policy"}` |

Cada veredicto queda en `logs/audit.jsonl` (`tony audit`), y cada tarea en
`logs/tasks/<task_id>.jsonl`. Nada de esto usa el modelo para decidir: la política es un YAML que
lees y editas tú.

---

## El orbe: en qué estado está Tony

En la app de escritorio, el orbe central siempre refleja un estado — no hace falta leer logs para
saber qué está haciendo Tony:

```
 ┌─────────────┐
 │    IDLE     │
 └─────────────┘
        │  nivel de voz alto en el micrófono
        ▼
 ┌─────────────┐
 │ ESCUCHANDO  │
 └─────────────┘
        │  Jarvis empieza a responder (turno/tarea en curso)
        ▼
 ┌─────────────┐
 │  PENSANDO   │
 └─────────────┘
        │  llega audio de la respuesta (voice_level output)
        ▼
 ┌─────────────┐
 │  HABLANDO   │
 └─────────────┘
        │  300 ms sin audio nuevo → vuelve a IDLE
        ▼
 ┌─────────────┐
 │    IDLE     │
 └─────────────┘
```

En cualquiera de esos estados, si Edith necesita que decidas algo, el ciclo se interrumpe:

```
 ┌─────────────┐
 │ CONFIRMANDO │
 └─────────────┘
        │  halo ámbar — espera "Permitir" o "Denegar"
```

`idle → listening → thinking → speaking → idle`, con `confirming` interrumpiendo el ciclo en
cuanto Edith necesita que decidas algo. El tamaño del orbe sigue el nivel de voz; sin WebGL se ve
una versión estática pero el estado se sigue notando por el halo y el color.

---

## Agentes, skills y subagentes

```
agents/
├── jarvis/
│   └── agent.md             # role: front — conversa, delega con `delegate`
├── viernes/
│   ├── agent.md              # role: worker — ejecuta tareas
│   ├── tool/tool.json        # qué servidores MCP y tools nativas tiene
│   ├── skills/                # procedimientos que lee bajo demanda
│   │   ├── correo/SKILL.md
│   │   ├── calendario/SKILL.md
│   │   ├── drive/SKILL.md
│   │   └── obsidian/SKILL.md
│   └── subagents/
│       └── resumidor/        # un worker más, un nivel de profundidad
│           ├── agent.md
│           └── tool/tool.json
└── edith/
    ├── agent.md               # role: guard — solo redacta la pregunta de confirmación
    └── policy.yaml            # la política real: allow / confirm / deny
```

- **`agent.md`**: frontmatter (`name`, `role`, `model`, `persona`, `voice.tts`) + el prompt de
  sistema en Markdown.
- **`tool.json`**: qué servidores MCP tiene el agente (`command`/`args`/`env` para stdio, o
  `url`/`headers` para HTTP) y qué tools nativas (`read_skill`, `run_subagent`). Nunca contiene
  permisos — esos viven solo en `policy.yaml`.
- **Skills** (`skills/<nombre>/SKILL.md`): procedimientos en Markdown que el agente lee bajo
  demanda con `tony.read_skill`; se listan en su prompt pero el cuerpo no se carga hasta que hace
  falta.
- **Subagentes** (`subagents/<nombre>/`): un worker más, con su propio `tool.json`, invocado con
  `tony.run_subagent`; comparte el id de tarea, el log y el presupuesto de tiempo de la tarea
  padre, y Edith evalúa sus tools igual que las del agente principal.

## Edith: la política de permisos

```yaml
default: confirm
rules:
  - match: "filesystem.read_*"          # patrón fnmatch, o lista de patrones
    verdict: allow
  - match: "filesystem.write_file"
    verdict: confirm
    when:
      path_outside: ["~/notas", "~/proyectos"]   # solo confirma si sale de esas carpetas
  - match: "gmail.send_email"
    verdict: confirm
  - match: "shell.run"
    verdict: deny
    when:
      args_regex: "(rm -rf|sudo)"
limits: {tool_timeout_s: 20, task_timeout_s: 300, confirm_timeout_s: 60}
auth: {pin_required: true, lock_after_min: 30}
```

Las reglas se recorren en orden; gana la primera cuyo patrón encaja con la tool (`<servidor>.
<tool>` o `tony.<nativa>`) **y** cuyas condiciones `when` se cumplen todas. Sin ninguna regla
ganadora, manda `default`. Es determinista: la misma llamada, con la misma política, siempre da el
mismo veredicto — no hay modelo de por medio en la decisión.

Las tareas delegadas exigen además que la sesión esté desbloqueada con un **PIN** (`tony pin set`,
guardado como hash argon2, nunca en claro), y toda decisión queda en `logs/audit.jsonl`
(`tony audit`). Detalle completo de reglas, `when`, PIN y auditoría en la
[referencia técnica](#referencia-técnica) más abajo.

---

## Instalación

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/) y Node.js ≥ 20 con `npm`/`npx`
(para el servidor MCP de ficheros y para compilar la interfaz). Para el modelo real hacen falta
credenciales de Claude disponibles para el Claude Agent SDK.

```bash
uv sync
uv run tony --help
```

Compilar la interfaz de la app de escritorio (una vez; Node solo hace falta para compilar, la app
no abre ningún servidor):

```bash
npm --prefix tony/apps/desktop/web ci && npm --prefix tony/apps/desktop/web run build
```

Voz e integración con el escritorio son extras opcionales:

```bash
uv sync --extra voice --extra desktop
```

Tony usa como raíz el directorio de `TONY_HOME` o, si no existe, el directorio actual.

## Uso rápido

```bash
uv run tony                          # abre la app de escritorio (orbe + chat)
uv run tony chat                     # conversación por terminal
uv run tony run viernes "Lista mis notas"   # ejecuta una tarea puntual y la imprime en JSON
uv run tony agents                   # qué agente ocupa cada rol, con su modelo y voz
uv run tony mcp list                 # conecta y lista los servidores MCP de cada agente
uv run tony audit --today            # auditoría de permisos de hoy
uv run tony pin set                  # fija el PIN de Edith
```

---

## Referencia técnica

Lo de abajo es la documentación exhaustiva: cada campo, cada regla, cada mensaje de error. Si
solo quieres entender qué es Tony y cómo fluye una tarea, con lo de arriba ya tienes lo esencial.

### `config/tony.yaml`

Opcional. Las claves que falten toman su valor por defecto y las desconocidas se rechazan con un
error que nombra el fichero y el campo. El fichero incluido documenta todos los valores por
defecto: agentes `front`/`worker`/`guard`, `reply_mode` (`auto|voice|text|both`), alias de modelos
(`claude-haiku`, `claude-sonnet`), `voice` y `desktop`.

### `config/.env`

Opcional y fuera de git. Contiene solo secretos (`NOMBRE=valor`); el entorno del proceso tiene
prioridad. Los valores llegan a los servidores MCP mediante marcadores `${NOMBRE}` en `tool.json`,
resueltos al arrancar cada servidor con `config/.env` y el entorno del proceso. Plantilla:
`config/.env.example`.

Qué es un secreto:

- todo valor no vacío definido en `config/.env` (aunque ningún servidor lo use);
- el valor de cualquier marcador cuyo nombre de variable encaje con
  `(?i)(token|key|secret|password|passwd|authorization|pin)`, venga de donde venga.

Los secretos se sustituyen por `***` en los resultados de tools, el log de tareas, la auditoría y
la salida de la CLI. Las demás variables del proceso (por ejemplo `${HOME}`) se resuelven pero no
se enmascaran.

### Agentes: `agents/<nombre>/`

```
agents/viernes/
├── agent.md          # frontmatter YAML + prompt de sistema en Markdown
└── tool/tool.json    # servidores MCP y tools nativas
agents/edith/
├── agent.md          # role: guard; redacta las preguntas de confirmación
└── policy.yaml       # política de permisos (Edith no tiene carpeta tool/)
```

`agent.md` exige exactamente estos campos: `name` (igual a la carpeta), `role`
(`front|worker|guard`), `model` (un alias de `config/tony.yaml`), `persona.language`,
`persona.tone` y `voice.tts` (`kokoro/<voz>` o una mezcla `kokoro/<voz>,<voz>`, p. ej.
`kokoro/ef_dora,bf_emma`, que promedia esas voces de Kokoro), más el campo opcional `description`
(texto no vacío). El cuerpo es el prompt de sistema y no puede estar vacío.

`tool/tool.json`:

```json
{
  "mcpServers": {
    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "${HOME}/notas"]},
    "remote": {"url": "https://example.test/mcp", "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"}}
  },
  "native": ["read_skill", "run_subagent"]
}
```

Cada servidor define `command` (stdio, con `args` y `env` opcionales) o `url` (HTTP streamable,
con `headers` opcionales), nunca ambos. Las tools se identifican como `<servidor>.<tool>`; el
nombre de servidor `tony` está reservado para las tools nativas (`tony.<nombre>`). Las claves
`allow` y `confirm` se rechazan: los permisos pertenecen a `agents/edith/policy.yaml`. Los nombres
de servidor solo admiten letras y dígitos separados por un único `-` o `_` (sin `.` ni `__`). Las
tools nativas disponibles son `read_skill` y `run_subagent`.

#### Skills: `agents/<agente>/skills/<nombre>/SKILL.md`

Una skill es una carpeta con un `SKILL.md`: frontmatter con exactamente `name` (igual a la
carpeta) y `description` (no vacía), seguido de un cuerpo Markdown no vacío.

```markdown
---
name: resumir
description: Resume notas en tres viñetas
---
Paso 1...
```

Si el agente declara la nativa `read_skill`, su prompt de sistema termina con una sección
`## Skills` con una línea `- <nombre>: <descripción>` por skill (nunca el cuerpo). El agente lee el
cuerpo bajo demanda con `tony.read_skill` (`{"name": "resumir"}`); un nombre desconocido devuelve
`skill '<nombre>' not found; available: ...`. Las skills se leen del disco al empezar cada tarea o
turno, así que una carpeta nueva se usa en la siguiente tarea sin reiniciar. Una skill inválida se
omite y genera un evento `error` (origen `skills`) que nombra el fichero.

#### Subagentes: `agents/<agente>/subagents/<nombre>/`

Un subagente tiene la misma estructura que un agente (`agent.md`, `tool/tool.json`, `skills/`
opcional) con `role: worker` y `description` obligatoria; su `tool.json` no puede declarar
`run_subagent` (profundidad 1). Si el agente declara `run_subagent`, su prompt termina con una
sección `## Subagentes` (`- <nombre>: <descripción>`) y puede llamar a `tony.run_subagent` con
`{"name": "resumidor", "tarea": {"objetivo": "..."}}`; recibe el resultado estructurado
`{resumen, datos, pasos, errores}` del subagente.

El subagente se ejecuta dentro de la tarea padre: comparte su id, su log
`logs/tasks/<task_id>.jsonl` (entre `subagent_started` y `subagent_finished`), sus límites y su
cómputo de tokens. Cada llamada suya pasa por Edith y se audita con `agent: "<agente>/<nombre>"`, y
el panel Actividad la muestra bajo un nodo hijo de la tarea. `tony.run_subagent` no está limitado
por `limits.tool_timeout_s`: lo limita el `task_timeout_s` de la tarea padre, y cancelar la tarea
padre detiene al subagente y cierra sus servidores MCP.

### Edith: política de permisos, en detalle

Toda llamada a una tool de un worker, MCP (`<servidor>.<tool>`) o nativa (`tony.<nombre>`), la
juzga Edith antes de ejecutarse con la política `agents/<guard>/policy.yaml` (`guard` de
`config/tony.yaml`, `edith` por defecto). La decisión es determinista y no usa ningún modelo. Una
política ausente o inválida detiene `tony run` antes de arrancar el worker, con el fichero y el
campo en el error.

```yaml
default: confirm              # allow | confirm | deny, obligatorio
rules:                        # en orden; gana la primera que aplica
  - match: "filesystem.write_file"         # patrón fnmatch, o lista de patrones
    verdict: confirm
    id: escritura-fuera                    # opcional; por defecto "<primer patrón>/<verdict>"
    when:                                  # opcional; deben cumplirse todas
      path_outside: ["~/notas", "~/proyectos"]
      args_regex: "(rm -rf|sudo)"
      numeric_above: {arg: importe, value: 100}
limits: {tool_timeout_s: 20, task_timeout_s: 300, confirm_timeout_s: 60,
         max_denied_retries: 3, token_alert: 50000, max_steps_per_agent: 30}
auth: {pin_required: true, lock_after_min: 30}   # ver «PIN de Edith»
```

Orden de evaluación: se recorren las reglas en orden de fichero; gana la primera cuyo patrón
encaja con el id de la tool (`fnmatch`, distingue mayúsculas) y cuyas condiciones `when` se cumplen
todas. Si ninguna gana se aplica `default` con la regla `default`. Las claves desconocidas se
rechazan en cualquier nivel.

- `path_outside`: se cumple si algún valor de texto de `path`, `source`, `destination` o de la
  lista `paths`, tras expandir `~` y normalizar, no está dentro (ni es igual) de ninguna carpeta de
  la lista. Sin rutas no se cumple. No resuelve enlaces simbólicos.
- `args_regex`: se cumple si `re.search` encaja con algún valor de texto de los argumentos,
  también anidado (las claves no cuentan).
- `numeric_above`: se cumple si `args[arg]` es un número (no booleano) estrictamente mayor que
  `value`.

Veredictos:

- `allow`: la tool se ejecuta (con `limits.tool_timeout_s`).
- `deny`: no se ejecuta y el agente recibe `{"error": "blocked_by_policy", "rule": "<regla>"}`. La
  tercera denegación de la misma tool en una tarea (`max_denied_retries`) cancela la tarea.
- `confirm`: Edith pregunta al usuario `Acción: <qué>. Regla: <regla>. ¿Autoriza?` (redactada por
  su modelo; si falla o tarda más de 5 s se usa una plantilla fija). En `tony run` la pregunta sale
  por stderr y la respuesta se lee de stdin: `s`, `si`, `sí`, `y` o `yes` (sin distinguir mayúsculas
  ni espacios) autorizan; cualquier otra respuesta, el fin de la entrada o no responder en
  `confirm_timeout_s` cancelan la tarea.

Una tarea cancelada (confirmación rechazada, denegaciones repetidas o más de
`max_steps_per_agent` llamadas de un agente) se detiene, cierra sus servidores MCP y devuelve
`resumen` vacío con el motivo en `errores`; `tony run` sale con código 1. Si los tokens de la
tarea superan `token_alert` se registra un único evento `token_alert`, sin cancelar.

La política incluida y sus casos de prueba offline están en `agents/edith/policy.yaml` y
`evals/politica.yaml`.

#### PIN de Edith

Con `auth.pin_required: true` (el valor de la política incluida) las tareas delegadas exigen que
la sesión de Edith esté desbloqueada con un PIN. Se guarda una sola vez:

```bash
uv run tony pin --help
uv run tony pin set      # pide el PIN dos veces sin mostrarlo; mínimo 4 caracteres
```

`tony pin set` guarda solo el hash argon2 del PIN en `config/edith.lock` (permisos `0600`,
ignorado por git) y sustituye el anterior; si las dos entradas no coinciden o el PIN es corto sale
con error sin tocar el fichero. El PIN nunca se escribe en claro en ficheros, logs, eventos ni
salida.

- Al arrancar (`tony chat` o la app de escritorio) se pide el PIN; en la app aparece un diálogo con
  el campo oculto y un botón de cancelar.
- Tras el 3.er PIN erróneo seguido hay que esperar 10 s, tras el 4.º 30 s y a partir del 5.º 60 s;
  un intento durante la espera se rechaza sin comprobarlo ni contarlo. Un PIN correcto pone el
  contador a cero.
- Modo solo conversación: si se cancela el PIN, o no existe `config/edith.lock` (o no es un hash
  válido), el agente de conversación sigue respondiendo pero `delegate` devuelve
  `{"error": "locked"}` sin pedir el PIN. Se puede desbloquear después con `/pin` en `tony chat` o
  con el botón «Introducir PIN» de la app.
- Rebloqueo por inactividad: si llega un mensaje `lock_after_min` minutos (30 por defecto) o más
  después del anterior, la sesión se bloquea y el PIN se pide en el siguiente `delegate`, que
  espera hasta `confirm_timeout_s`; cancelar o no responder devuelve `{"error": "locked"}`. La
  inactividad se mide entre mensajes, no entre pulsaciones.
- Con `pin_required: false` no se pide nunca.

#### Auditoría: `logs/audit.jsonl`

Cada veredicto añade una línea JSON con `ts` (UTC), `task_id`, `agent`, `tool`, `args_hash`
(SHA-256 de los argumentos en JSON canónico), `args_preview` (JSON canónico con secretos
enmascarados y claves con aspecto de secreto como `***`, recortado a 200 caracteres), `verdict`,
`rule`, `user_decision` (`allow|deny|timeout` en `confirm`, `null` en el resto) y `duration_ms`
(incluida la espera de confirmación).

```bash
uv run tony audit --help
uv run tony audit                    # todas las líneas, de la más antigua a la más reciente
uv run tony audit --today            # solo las de hoy (fecha local)
uv run tony audit --verdict deny     # allow | confirm | deny
```

`tony audit` imprime una tabla con `ts`, `agent`, `tool`, `verdict`, `rule` y `user_decision`; sale
con código 0 aunque no haya líneas o el fichero no exista, y avisa por stderr de las líneas mal
formadas que omite.

### Uso del CLI, en detalle

```bash
uv run tony run --help
uv run tony run viernes "Lista mis notas"
```

`tony run <agente> "<tarea>"` ejecuta un agente `worker` con la tarea como `objetivo` e imprime en
stdout un único objeto JSON `{resumen, datos, pasos, errores}`. Sale con código 0 si `errores` está
vacío, 1 si el resultado trae errores y 2 si la definición del agente o la tarea no son válidas (el
error, con fichero y campo, va a stderr).

Límites: 10 s de conexión por servidor MCP; el tiempo por llamada a tool y por tarea sale de
`limits` en la política (20 s y 300 s por defecto). Cada tarea deja su registro en
`logs/tasks/<task_id>.jsonl` y el stderr de cada servidor stdio en `logs/mcp/<servidor>.log`.

### App de escritorio

```bash
uv run tony              # sin subcomando abre la ventana (uv run tony --help sigue mostrando la ayuda)
```

Una sola ventana nativa (sin barra del sistema operativo: la dibuja la propia interfaz, con
arrastre y botones minimizar/maximizar/cerrar propios) que muestra la interfaz web de Tony,
compilada en `tony/apps/desktop/web/dist/` y cargada desde un fichero local: no se abre ningún
servidor ni puerto, ni un navegador aparte. El núcleo (Jarvis, Viernes, Edith) corre en su propio
hilo; la página solo envía comandos JSON (validados antes de llegar al núcleo) y recibe eventos, de
modo que un fallo del núcleo (modelo caído, servidor MCP roto, excepción) se muestra como error en
el chat y la ventana sigue abierta. El audio no pasa por la página: el núcleo solo le envía niveles
(`voice_level`) para animar el orbe.

- **Orbe**: en el centro, detrás del chat. Su estado sale de los eventos (ver [el orbe](#el-orbe-en-qué-estado-está-tony)
  más arriba); su tamaño sigue el nivel del micrófono o de la voz. Sin WebGL se muestra un orbe
  estático y el resto funciona igual.
- **Chat**: mensajes por agente, con el color de cada uno (ver la [tabla de agentes](#qué-es)) y el
  resto (incluido el usuario) en gris. Las respuestas crecen a medida que llegan y se muestran como
  Markdown (con tablas; el HTML en bruto se escapa). Intro envía el mensaje; el selector
  `auto/voice/text/both` cambia el modo de respuesta y el botón de micrófono escucha una frase (ver
  [Voz](#voz)).
- **Actividad** (plegable): cada tarea delegada con su agente y objetivo, sus llamadas a tools con
  veredicto (y decisión del usuario), las de subagentes agrupadas bajo su nodo, mostradas con la
  más reciente primero.
- **MCPs** (plegable): cada servidor MCP conectado por agente, con su estado (en rojo si está
  caído) y un icono de información con una breve descripción. Al arrancar se comprueba en segundo
  plano cada servidor de Jarvis y Viernes.
- **Edith** (plegable): la auditoría de hoy (fecha local, sin argumentos de las tools) filtrable
  por veredicto, con las llamadas nuevas añadidas al vuelo.
- **Tarjeta de confirmación**: sobre el orbe, con la pregunta pendiente y los botones «Permitir»,
  «Denegar» y, cuando procede, «Permitir siempre»; el foco empieza en «Denegar».

«Permitir siempre» solo aparece si ninguna regla `deny` de la política tiene un patrón que encaje
con la tool pendiente (sin mirar sus condiciones `when`); por eso nunca se ofrece, por ejemplo,
para `shell.run`. Al pulsarlo se ejecuta la llamada y se añade como primera regla de
`agents/<guard>/policy.yaml`:

```yaml
- match: filesystem.delete_file
  verdict: allow
  id: user-always/filesystem.delete_file
```

A partir de ahí esa tool se permite sin preguntar en la tarea actual y en las siguientes. La
política se valida antes de sustituir el fichero de forma atómica; al reescribirla se pierden los
comentarios del YAML (el orden y el contenido de las reglas se conservan). Para revocarlo, borre la
regla `user-always/<tool>` del fichero. Si no se puede escribir la política, la llamada se permite
una vez y se muestra un error.

El PIN se pide en una capa sobre la página al arrancar (y en el rebloqueo por inactividad) con el
campo oculto, la cuenta atrás de la espera tras fallos y un botón de cancelar; sin
`config/edith.lock` solo muestra cómo crear el PIN con `tony pin set`. Mientras Edith esté
bloqueada, el botón «Introducir PIN» vuelve a abrirla. El PIN se envía una sola vez y el campo se
vacía al momento; la página no lo guarda. Cerrar la ventana cancela la tarea en curso, cierra los
servidores MCP y detiene el núcleo.

Si la interfaz no está compilada, la ventana muestra la orden para compilarla
(`npm --prefix tony/apps/desktop/web ci && npm --prefix tony/apps/desktop/web run build`); la voz,
la bandeja, la instancia única, `tony --focus`, el atajo y las notificaciones siguen funcionando.
La página está aislada: se le deniegan todos los permisos (micrófono, cámara, ubicación,
notificaciones…), no puede salir de su `index.html` ni cargar recursos remotos, y los enlaces
`http`/`https` de las respuestas se abren en el navegador del sistema (los demás se ignoran).

#### Integración con el escritorio

Requiere el extra `desktop` (`uv sync --extra desktop`) para el atajo global y las notificaciones;
sin él la app funciona igual y lo indica en el chat cuando haría falta.

- **Bandeja del sistema** (`desktop.tray: true` por defecto en `config/tony.yaml`): icono con
  «Mostrar/Ocultar» (oculta o muestra la ventana; el núcleo sigue trabajando) y «Salir» (igual que
  cerrar la ventana). El icono y el tooltip muestran el estado: gris `Tony — en espera`, azul
  `Tony — trabajando` (turno o tarea en curso) y ámbar `Tony — esperando confirmación`. Con
  `desktop.tray: false`, o si el escritorio no ofrece bandeja, no se crea.
- **Una sola instancia**: un segundo `tony` muestra y levanta la ventana ya abierta y termina con
  código 0. El canal es un socket local solo accesible por su usuario
  (`$XDG_RUNTIME_DIR/tony-desktop.sock`) que solo acepta los mensajes `show` y `focus`.
- **`tony --focus`**: muestra, restaura y enfoca la ventana y empieza a escuchar (si no hay
  ninguna abierta, abre la app y escucha en cuanto la voz esté `ready`; si la voz no está
  disponible lo dice en el chat). `--focus` no se combina con subcomandos.
- **Atajo global en X11** (`desktop.hotkey`, `Super+J` por defecto): hace lo mismo que
  `tony --focus`. Sintaxis: modificadores `Super` (o `Meta`/`Win`), `Ctrl`, `Alt`, `Shift` unidos
  con `+` y una tecla (letra, dígito, `F1`–`F12`, `Space`, `Enter`, `Tab` o `Esc`), sin distinguir
  mayúsculas: `Ctrl+Alt+Space`, `Super+F2`. Un atajo inválido se muestra como error nombrando
  `desktop.hotkey` y la app sigue funcionando. Solo se registra con `XDG_SESSION_TYPE=x11`.
- **Wayland**: no hay atajos globales para aplicaciones (ver [Atajos en
  Wayland](#atajos-en-wayland)).
- **Notificaciones**: si Edith espera una confirmación con la ventana oculta o minimizada, se
  muestra una notificación nativa `Tony — Edith` con la pregunta (con los secretos ya enmascarados;
  puede verse en la pantalla de bloqueo). Al pulsarla se abre la ventana en la tarjeta de
  confirmación con el foco en «Denegar». Sin servicio de notificaciones se muestra un error
  `notifications` una vez y la tarjeta de la ventana sigue funcionando.

##### Atajos en Wayland

Cree un atajo personalizado del escritorio que ejecute `tony --focus` (con el Flatpak,
`flatpak run io.github.renzoramosdev.Tony --focus`):

- KDE Plasma: Preferencias del sistema → Teclado → Accesos rápidos → Añadir nuevo → Orden o
  script, con esa orden y el atajo que prefiera (p. ej. Meta+J).
- GNOME: Configuración → Teclado → Ver y personalizar atajos → Atajos personalizados → «+», con
  esa orden y el atajo que prefiera.

### Voz

La voz es local: micrófono a 16 kHz mono, detección de voz con Silero VAD, transcripción en
español con faster-whisper (`voice.stt`, `faster-whisper/small` en `int8` sobre CPU) y síntesis con
Kokoro a 24 kHz. Se instala con el extra `voice` (torch solo CPU) y necesita la biblioteca del
sistema PortAudio (`portaudio` en Fedora, `libportaudio2` en Debian/Ubuntu):

```bash
uv sync --extra voice --extra desktop
```

Al abrir la app se cargan en segundo plano el VAD, el modelo de transcripción y las voces de los
tres agentes; la ventana responde mientras tanto. El estado se publica como evento `voice_state`:
`loading`, `ready`, `listening` o `unavailable` con el motivo (extra no instalado, `voice.stt`
distinto de `faster-whisper/<modelo>`, `voice.vad` distinto de `silero` o un fallo al cargar). Sin
voz todo sigue funcionando por texto y el tooltip del micrófono dice por qué.

Los dispositivos de entrada/salida que se listan son los reales del sistema (vía PipeWire), los
mismos que ves en los ajustes de audio — no las duplicidades internas de ALSA ni los flujos de
otras apps.

Micrófono: con la voz `ready`, un clic escucha **una** frase: se cierra tras 700 ms de silencio (o
a los 30 s), se transcribe y se envía a Jarvis como un mensaje escrito, con origen `voice` (en el
chat aparece como «Tú (voz)»). Mientras escucha el botón muestra «Escuchando…» y otro clic lo para;
sin hablar en 10 s se cierra solo. Empezar a escuchar corta lo que Tony esté diciendo, así que
nunca se graba a sí mismo. `cancel` detiene también la voz y la escucha.

Modo de respuesta y voz:

| Modo | Habla | Escribe |
|------|-------|---------|
| `voice` | sí | no |
| `text` | no | sí |
| `both` | sí | sí |
| `auto` | si el mensaje llegó por voz | si llegó escrito |

Si la voz no está `ready` el turno siempre se escribe. En un turno que solo habla, el chat muestra
la respuesta completa al terminar el turno.

Qué se dice: la respuesta se parte en frases mientras llega y cada frase suena en cuanto está
completa. Los bloques de código y las tablas Markdown se sustituyen por «Te lo dejo en pantalla.»;
las respuestas de más de 600 caracteres se dicen como sus dos primeras frases seguidas de esa misma
frase; las marcas Markdown (negritas, títulos, viñetas, comillas invertidas, destinos de enlaces)
no se leen.

Voces por agente (`voice.tts` de cada `agent.md`): Jarvis `kokoro/em_alex`, Viernes `kokoro/
ef_dora` y Edith `kokoro/ef_dora,bf_emma`. Una lista separada por comas es una mezcla: la media de
esas voces de Kokoro.

Edith por voz: si una confirmación queda pendiente durante un turno que habla, Edith la pregunta
con su voz (sin la parte `Regla: …`) y, cuando termina de sonar, el micrófono escucha la respuesta.
Solo «Sí, Edith» (sin importar mayúsculas, tildes ni puntuación: `si edith`) permite; cualquier
otra frase deniega; el silencio hasta `confirm_timeout_s` es `timeout`. El aviso de la ventana sigue
disponible y responder ahí cierra la escucha.

Privacidad: el audio nunca sale del proceso, no se guarda en disco ni se publica como evento; solo
el texto transcrito llega al chat y al historial.

### Conversación: `tony chat`

```bash
uv run tony chat --help
uv run tony chat
uv run tony agents       # slot, agente, rol, modelo y voz de front, worker y guard
```

`tony chat` lee un mensaje por línea y se lo envía al agente de conversación (`front` de
`config/tony.yaml`, Jarvis por defecto); la respuesta aparece en stdout a medida que llega, con el
prefijo `Jarvis: `. Las líneas vacías se ignoran y el chat termina con `/salir` o al acabar la
entrada. Si el modelo falla se muestra `tony: <error>` en stderr y el chat continúa.

Jarvis encarga las tareas a Viernes con la tool `delegate` y explica su resultado; si una tarea
tarda más de 3 s se muestra una vez `Un momento, señor; estoy en ello.`. Las confirmaciones de
Edith salen por stderr con el prefijo `Edith: ` y se responden en la misma entrada (una línea
tardía tras agotarse la espera llega a Jarvis como mensaje, no se pierde).

Comandos y prefijos:

- `/pin`: vuelve a pedir el PIN de Edith (por ejemplo tras cancelarlo).
- `/salir`: termina el chat.
- `/v <mensaje>` y `/t <mensaje>`: responden a ese mensaje por voz o por texto sin cambiar el modo
  guardado (el prefijo se quita antes de enviarlo).

Modo de respuesta: `auto`, `voice`, `text` o `both`. Se cambia pidiéndoselo a Jarvis (tool
`set_reply_mode`) o con el selector de la app, y se guarda como `reply_mode: <modo>` en
`memory/preferences.md`; si no hay línea válida se usa `reply_mode` de `config/tony.yaml`. En
`tony chat` las respuestas siempre se escriben; la voz solo existe en la app de escritorio (ver
[Voz](#voz)).

Memoria local (ignorada por git):

- `memory/preferences.md`: preferencias que Jarvis guarda con la tool `remember` (líneas
  `- <texto>`, con secretos enmascarados). Se añade a su prompt en cada mensaje, así que las
  ediciones a mano se aplican al siguiente mensaje.
- `memory/conversations.sqlite`: historial (tabla `messages`). Cada arranque de `tony chat` o de la
  app abre una conversación nueva; a cada mensaje se le envían los 20 mensajes anteriores de la
  conversación actual. Los resultados de Viernes no se guardan como mensajes.

### Servidores MCP: `tony mcp`

```bash
uv run tony mcp --help
uv run tony mcp add notas npx --arg -y --arg @modelcontextprotocol/server-filesystem \
    --arg '${HOME}/notas' --env LOG=1 --agent viernes
uv run tony mcp add remoto https://example.test/mcp \
    --header 'Authorization=Bearer ${REMOTE_TOKEN}' --agent viernes
uv run tony mcp add notas npx --agent viernes/resumidor   # tool.json de un subagente
uv run tony mcp list                  # todos los agentes y subagentes
uv run tony mcp list --agent viernes
```

`tony mcp add <nombre> <comando-o-url> --agent <agente>` añade el servidor al `tool.json` del
agente (o de `<agente>/<subagente>`) sin tocar el resto de claves ni su orden e imprime
`added <nombre> to <fichero>`. Un destino que empieza por `http://` o `https://` crea una entrada
HTTP (`url` y `--header K=V` repetible); cualquier otro, una entrada stdio (`command`, `--arg` y
`--env K=V` repetibles). Mezclar opciones de otro transporte, un par sin `=` o con la clave vacía,
un nombre ya existente, un nombre inválido (`tony`, con `.` o `__`), un agente inexistente o
guardián, o un resultado que no valide terminan con error y dejan el fichero intacto. Las escrituras
se serializan con un bloqueo exclusivo sobre `tool.json.lock` (espera como máximo 5 s) y sustituyen
el fichero de forma atómica (JSON UTF-8 con sangría de 2 espacios).

Los `${VAR}` se escriben tal cual y se resuelven al conectar, desde el entorno o `config/.env`. Si
la clave de un `--header` o `--env` parece un secreto (`token`, `key`, `secret`, `password`,
`passwd`, `authorization`, `pin`) y su valor no usa `${...}`, la entrada se escribe igualmente y
stderr avisa recomendando un `${VAR}` definido en `config/.env`; los valores nunca se imprimen.

`tony mcp list [--agent <agente>]` conecta cada servidor declarado con las mismas reglas que una
tarea, imprime la tabla `agent server state tools` (`ok` o `error: <motivo enmascarado>`, y el
número de tools) y cierra todas las conexiones. Sale con 0 aunque haya servidores caídos; un
`--agent` inexistente o un `tool.json` inválido (que se nombra en stderr mientras se listan los
demás) dan un código distinto de 0.

### Recarga en caliente

La app de escritorio y `tony chat` vigilan (con `watchfiles`) cada `agents/<agente>/tool/tool.json`,
cada `agents/<agente>/subagents/<sub>/tool/tool.json` y el `agents/<guard>/policy.yaml`, también los
creados después de arrancar; el resto de ficheros (incluido `tool.json.lock`) se ignora. `tony run`
no vigila nada: cada ejecución ya lee los ficheros al empezar.

- Un cambio válido de `policy.yaml` se aplica a la siguiente llamada a una tool, incluso dentro de
  una tarea en curso. Los `limits` (salvo `confirm_timeout_s`) se aplican desde la siguiente tarea
  y `auth` desde la siguiente sesión.
- Un cambio válido de un `tool.json` se usa en la siguiente tarea o turno; la tarea en curso
  conserva los servidores con los que empezó. Solo se conectan (y se cierran) los servidores
  añadidos o modificados para actualizar su estado; los eliminados aparecen caídos con el motivo
  `removed from tool.json`.
- Un cambio inválido (YAML o JSON roto, error de esquema o fichero borrado) mantiene la última
  configuración válida, publica un evento `error` (origen `reload`) y escribe en stderr
  `tony: warning: <fichero>: <error>`. El siguiente guardado válido se aplica con normalidad.

Las skills y los subagentes no necesitan vigilancia: se leen del disco en cada tarea o turno.

## Flatpak

`packaging/` contiene el manifiesto `io.github.renzoramosdev.Tony` (runtime KDE 6.8 con Python
3.12, PortAudio compilado como módulo y Tony con los extras `voice` y `desktop`), el fichero
`.desktop` (con la acción «Escuchar», `tony --focus`) y el icono. Es para compilar en local: las
dependencias de Python se descargan durante la compilación y se verifican con los hashes de
`packaging/requirements.txt`, y la interfaz web se compila dentro de la compilación con la
extensión `org.freedesktop.Sdk.Extension.node20` (`npm ci` y `npm run build`, con los paquetes
fijados por `package-lock.json`). Tras cambiar dependencias de Python, regenérelo:

```bash
uv export --frozen --no-dev --extra voice --extra desktop --no-emit-project -o packaging/requirements.txt
flatpak-builder --user --install --force-clean build-dir packaging/io.github.renzoramosdev.Tony.yml
flatpak run io.github.renzoramosdev.Tony            # abre la app
flatpak run io.github.renzoramosdev.Tony --focus    # la levanta y escucha
```

Permisos del sandbox: Wayland (con X11 de reserva), PulseAudio (micrófono y altavoces), red, el
directorio personal, el servicio de notificaciones, la GPU (`--device=dri`, para el WebGL del orbe;
sin ella se ve el orbe estático) y `--env=QTWEBENGINE_DISABLE_SANDBOX=1`: el sandbox interno de
Chromium no puede arrancar dentro de bubblewrap con PySide6 instalado por pip, así que se desactiva
solo dentro del Flatpak (bubblewrap sigue siendo el sandbox exterior y la página solo ejecuta su
propio código local). Para usar otro `TONY_HOME`:

```bash
flatpak override --user --env=TONY_HOME=$HOME/Tony io.github.renzoramosdev.Tony
```

Servidores MCP dentro del sandbox: los que se lanzan con `npx` necesitan Node.js dentro del
Flatpak, que no viene incluido; use preferiblemente servidores que se lancen con `uvx` (Python: el
binario estático de `uv` instalado en `~/.local/bin` es accesible gracias a `--filesystem=home`;
indique su ruta completa como orden), o instale Node en el sandbox. Para el atajo de teclado en
Wayland, vea [Atajos en Wayland](#atajos-en-wayland).

## Desarrollo

```bash
uv run pytest            # offline; omite los tests marcados evals, voice y web
TONY_EVALS=1 uv run pytest tests/evals   # modelo real (requiere credenciales y npx)
uv run ruff check && uv run ruff format --check
npm --prefix tony/apps/desktop/web ci     # dependencias de la interfaz (una vez)
npm --prefix tony/apps/desktop/web test   # tests de la interfaz (vitest, sin GPU ni red)
npm --prefix tony/apps/desktop/web run build
uv run pytest -m web     # carga la interfaz compilada en Qt WebEngine sin pantalla
```
