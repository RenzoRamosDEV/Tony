# Tony

Asistente personal local con tres agentes de rol fijo: Jarvis (`front`), Viernes (`worker`) y
Edith (`guard`). Permite ejecutar a Viernes desde la CLI bajo la política de permisos de Edith.

## Instalación

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/) y, para el servidor MCP de ficheros
de Viernes, Node.js con `npx`. Para ejecutar con el modelo real hacen falta credenciales de
Claude disponibles para el Claude Agent SDK.

```bash
uv sync
uv run tony --help
```

Tony usa como raíz el directorio indicado en `TONY_HOME` o, si no existe, el directorio actual.

## Configuración

### `config/tony.yaml`

Opcional. Las claves que falten toman su valor por defecto y las desconocidas se rechazan con
un error que nombra el fichero y el campo. El fichero incluido documenta todos los valores por
defecto: agentes `front`/`worker`/`guard`, `reply_mode` (`auto|voice|text|both`), alias de
modelos (`claude-haiku`, `claude-sonnet`), `voice` y `desktop`.

### `config/.env`

Opcional y fuera de git. Contiene solo secretos (`NOMBRE=valor`); el entorno del proceso tiene
prioridad. Los valores llegan a los servidores MCP mediante marcadores `${NOMBRE}` en
`tool.json`, que se resuelven al arrancar cada servidor con `config/.env` y el entorno del
proceso. Plantilla: `config/.env.example`.

Qué es un secreto:

- todo valor no vacío definido en `config/.env` (aunque ningún servidor lo use);
- el valor de cualquier marcador cuyo nombre de variable encaje con
  `(?i)(token|key|secret|password|passwd|authorization|pin)`, venga de donde venga.

Los secretos se sustituyen por `***` en los resultados de tools, el log de tareas, la auditoría
y la salida de la CLI. Las demás variables del proceso (por ejemplo `${HOME}`) se resuelven pero
no se enmascaran.

## Agentes: `agents/<nombre>/`

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
`persona.tone` y `voice.tts` (`kokoro/<voz>`), más el campo opcional `description` (texto no
vacío). El cuerpo es el prompt de sistema y no puede estar vacío.

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
`allow` y `confirm` se rechazan: los permisos pertenecen a `agents/edith/policy.yaml`. Los
nombres de servidor solo admiten letras y dígitos separados por un único `-` o `_` (sin `.` ni
`__`). Las tools nativas disponibles son `read_skill` y `run_subagent`.

### Skills: `agents/<agente>/skills/<nombre>/SKILL.md`

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
`## Skills` con una línea `- <nombre>: <descripción>` por skill (nunca el cuerpo). El agente lee
el cuerpo bajo demanda con `tony.read_skill` (`{"name": "resumir"}`); un nombre desconocido
devuelve `skill '<nombre>' not found; available: ...`. Las skills se leen del disco al empezar
cada tarea o turno, así que una carpeta nueva se usa en la siguiente tarea sin reiniciar. Una
skill inválida se omite y genera un evento `error` (origen `skills`) que nombra el fichero.

### Subagentes: `agents/<agente>/subagents/<nombre>/`

Un subagente tiene la misma estructura que un agente (`agent.md`, `tool/tool.json`, `skills/`
opcional) con `role: worker` y `description` obligatoria; su `tool.json` no puede declarar
`run_subagent` (profundidad 1). Si el agente declara `run_subagent`, su prompt termina con una
sección `## Subagentes` (`- <nombre>: <descripción>`) y puede llamar a `tony.run_subagent` con
`{"name": "resumidor", "tarea": {"objetivo": "..."}}`; recibe el resultado estructurado
`{resumen, datos, pasos, errores}` del subagente.

El subagente se ejecuta dentro de la tarea padre: comparte su id, su log
`logs/tasks/<task_id>.jsonl` (entre `subagent_started` y `subagent_finished`), sus límites y su
cómputo de tokens. Cada llamada suya pasa por Edith y se audita con `agent: "<agente>/<nombre>"`,
y la zona de actividad la muestra bajo un nodo hijo de la tarea. `tony.run_subagent` no está
limitado por `limits.tool_timeout_s`: lo limita el `task_timeout_s` de la tarea padre, y cancelar
la tarea padre detiene al subagente y cierra sus servidores MCP.

## Edith: política de permisos

Toda llamada a una tool de un worker, MCP (`<servidor>.<tool>`) o nativa (`tony.<nombre>`), la
juzga Edith antes de ejecutarse con la política `agents/<guard>/policy.yaml` (`guard` de
`config/tony.yaml`, `edith` por defecto). La decisión es determinista y no usa ningún modelo.
Una política ausente o inválida detiene `tony run` antes de arrancar el worker, con el fichero y
el campo en el error.

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
encaja con el id de la tool (`fnmatch`, distingue mayúsculas) y cuyas condiciones `when` se
cumplen todas. Si ninguna gana se aplica `default` con la regla `default`. Las claves
desconocidas se rechazan en cualquier nivel.

- `path_outside`: se cumple si algún valor de texto de `path`, `source`, `destination` o de la
  lista `paths`, tras expandir `~` y normalizar, no está dentro (ni es igual) de ninguna carpeta
  de la lista. Sin rutas no se cumple. No resuelve enlaces simbólicos.
- `args_regex`: se cumple si `re.search` encaja con algún valor de texto de los argumentos,
  también anidado (las claves no cuentan).
- `numeric_above`: se cumple si `args[arg]` es un número (no booleano) estrictamente mayor que
  `value`.

Veredictos:

- `allow`: la tool se ejecuta (con `limits.tool_timeout_s`).
- `deny`: no se ejecuta y el agente recibe `{"error": "blocked_by_policy", "rule": "<regla>"}`.
  La tercera denegación de la misma tool en una tarea (`max_denied_retries`) cancela la tarea.
- `confirm`: Edith pregunta al usuario `Acción: <qué>. Regla: <regla>. ¿Autoriza?` (redactada
  por su modelo; si falla o tarda más de 5 s se usa una plantilla fija). En `tony run` la
  pregunta sale por stderr y la respuesta se lee de stdin: `s`, `si`, `sí`, `y` o `yes` (sin
  distinguir mayúsculas ni espacios) autorizan; cualquier otra respuesta, el fin de la entrada o
  no responder en `confirm_timeout_s` cancelan la tarea.

Una tarea cancelada (confirmación rechazada, denegaciones repetidas o más de
`max_steps_per_agent` llamadas de un agente) se detiene, cierra sus servidores MCP y devuelve
`resumen` vacío con el motivo en `errores`; `tony run` sale con código 1. Si los tokens de la
tarea superan `token_alert` se registra un único evento `token_alert`, sin cancelar.

La política incluida y sus casos de prueba offline están en `agents/edith/policy.yaml` y
`evals/politica.yaml`.

### PIN de Edith

Con `auth.pin_required: true` (el valor de la política incluida) las tareas delegadas exigen
que la sesión de Edith esté desbloqueada con un PIN. Se guarda una sola vez:

```bash
uv run tony pin --help
uv run tony pin set      # pide el PIN dos veces sin mostrarlo; mínimo 4 caracteres
```

`tony pin set` guarda solo el hash argon2 del PIN en `config/edith.lock` (permisos `0600`,
ignorado por git) y sustituye el anterior; si las dos entradas no coinciden o el PIN es corto
sale con error sin tocar el fichero. El PIN nunca se escribe en claro en ficheros, logs,
eventos ni salida.

- Al arrancar (`tony chat` o la app de escritorio) se pide el PIN; en la app aparece un diálogo
  con el campo oculto y un botón de cancelar.
- Tras el 3.er PIN erróneo seguido hay que esperar 10 s, tras el 4.º 30 s y a partir del 5.º
  60 s; un intento durante la espera se rechaza sin comprobarlo ni contarlo. Un PIN correcto
  pone el contador a cero.
- Modo solo conversación: si se cancela el PIN, o no existe `config/edith.lock` (o no es un hash
  válido), el agente de conversación sigue respondiendo pero `delegate` devuelve
  `{"error": "locked"}` sin pedir el PIN. Se puede desbloquear después con `/pin` en
  `tony chat` o con la acción «Desbloquear» de la app.
- Rebloqueo por inactividad: si llega un mensaje `lock_after_min` minutos (30 por defecto) o más
  después del anterior, la sesión se bloquea y el PIN se pide en el siguiente `delegate`, que
  espera hasta `confirm_timeout_s`; cancelar o no responder devuelve `{"error": "locked"}`.
  La inactividad se mide entre mensajes, no entre pulsaciones.
- Con `pin_required: false` no se pide nunca.

### Auditoría: `logs/audit.jsonl`

Cada veredicto añade una línea JSON con `ts` (UTC), `task_id`, `agent`, `tool`, `args_hash`
(SHA-256 de los argumentos en JSON canónico), `args_preview` (JSON canónico con secretos
enmascarados y claves con aspecto de secreto como `***`, recortado a 200 caracteres),
`verdict`, `rule`, `user_decision` (`allow|deny|timeout` en `confirm`, `null` en el resto) y
`duration_ms` (incluida la espera de confirmación).

```bash
uv run tony audit --help
uv run tony audit                    # todas las líneas, de la más antigua a la más reciente
uv run tony audit --today            # solo las de hoy (fecha local)
uv run tony audit --verdict deny     # allow | confirm | deny
```

`tony audit` imprime una tabla con `ts`, `agent`, `tool`, `verdict`, `rule` y `user_decision`;
sale con código 0 aunque no haya líneas o el fichero no exista, y avisa por stderr de las
líneas mal formadas que omite.

## Uso

```bash
uv run tony run --help
uv run tony run viernes "Lista mis notas"
```

`tony run <agente> "<tarea>"` ejecuta un agente `worker` con la tarea como `objetivo` e imprime
en stdout un único objeto JSON `{resumen, datos, pasos, errores}`. Sale con código 0 si
`errores` está vacío, 1 si el resultado trae errores y 2 si la definición del agente o la tarea
no son válidas (el error, con fichero y campo, va a stderr).

Límites: 10 s de conexión por servidor MCP; el tiempo por llamada a tool y por tarea sale de
`limits` en la política (20 s y 300 s por defecto). Cada tarea deja su registro en `logs/tasks/<task_id>.jsonl` y el stderr de cada servidor stdio en
`logs/mcp/<servidor>.log`.

### App de escritorio

```bash
uv run tony              # sin subcomando abre la ventana (uv run tony --help sigue mostrando la ayuda)
```

Una sola ventana con tres zonas. El núcleo (Jarvis, Viernes, Edith) corre en su propio hilo; la
ventana solo envía comandos JSON y recibe eventos, de modo que un fallo del núcleo (modelo
caído, servidor MCP roto, excepción) se muestra como error en el chat y la ventana sigue abierta.

- **Chat**: burbujas por agente, Jarvis `#2F6FED`, Viernes `#2E9E5B`, Edith `#E0A100` y el resto
  (incluido el usuario) en gris. Las respuestas crecen a medida que llegan y se muestran como
  Markdown (CommonMark con tablas; el HTML en bruto se escapa). Intro envía el mensaje; el
  selector `auto/voice/text/both` cambia el modo de respuesta; el botón de micrófono está
  desactivado porque la voz llegará más adelante.
- **Actividad** (plegable): cada tarea delegada con su agente y objetivo, sus llamadas a tools
  con veredicto (y decisión del usuario), las de subagentes agrupadas bajo su nodo, los tokens y
  el tiempo al terminar, y cada servidor MCP con su estado (en rojo si está caído). Al arrancar
  se comprueba en segundo plano cada servidor de Jarvis y Viernes.
- **Edith** (plegable): aviso con la pregunta pendiente y los botones «Permitir», «Denegar» y,
  cuando procede, «Permitir siempre»; debajo, la auditoría de hoy (fecha local) filtrable por
  veredicto.

«Permitir siempre» solo aparece si ninguna regla `deny` de la política tiene un patrón que
encaje con la tool pendiente (sin mirar sus condiciones `when`); por eso nunca se ofrece, por
ejemplo, para `shell.run`. Al pulsarlo se ejecuta la llamada y se añade como primera regla de
`agents/<guard>/policy.yaml`:

```yaml
- match: filesystem.delete_file
  verdict: allow
  id: user-always/filesystem.delete_file
```

A partir de ahí esa tool se permite sin preguntar en la tarea actual y en las siguientes. La
política se valida antes de sustituir el fichero de forma atómica; al reescribirla se pierden
los comentarios del YAML (el orden y el contenido de las reglas se conservan). Para revocarlo,
borre la regla `user-always/<tool>` del fichero. Si no se puede escribir la política, la llamada
se permite una vez y se muestra un error.

El diálogo del PIN aparece al arrancar (y en el rebloqueo por inactividad) con el campo oculto,
la cuenta atrás de la espera tras fallos y un botón de cancelar; sin `config/edith.lock` solo
muestra cómo crear el PIN con `tony pin set`. Mientras Edith esté bloqueada, el menú
«Desbloquear Edith» vuelve a abrirlo. Cerrar la ventana cancela la tarea en curso, cierra los
servidores MCP y detiene el núcleo.

### Conversación: `tony chat`

```bash
uv run tony chat --help
uv run tony chat
uv run tony agents       # slot, agente, rol, modelo y voz de front, worker y guard
```

`tony chat` lee un mensaje por línea y se lo envía al agente de conversación (`front` de
`config/tony.yaml`, Jarvis por defecto); la respuesta aparece en stdout a medida que llega, con
el prefijo `Jarvis: `. Las líneas vacías se ignoran y el chat termina con `/salir` o al acabar la
entrada. Si el modelo falla se muestra `tony: <error>` en stderr y el chat continúa.

Jarvis encarga las tareas a Viernes con la tool `delegate` y explica su resultado; si una tarea
tarda más de 3 s se muestra una vez `Un momento, señor; estoy en ello.`. Las confirmaciones de
Edith salen por stderr con el prefijo `Edith: ` y se responden en la misma entrada (una línea
tardía tras agotarse la espera llega a Jarvis como mensaje, no se pierde).

Comandos y prefijos:

- `/pin`: vuelve a pedir el PIN de Edith (por ejemplo tras cancelarlo).
- `/salir`: termina el chat.
- `/v <mensaje>` y `/t <mensaje>`: responden a ese mensaje por voz o por texto sin cambiar el
  modo guardado (el prefijo se quita antes de enviarlo).

Modo de respuesta: `auto`, `voice`, `text` o `both`. Se cambia pidiéndoselo a Jarvis (tool
`set_reply_mode`) o con el selector de la app, y se guarda como `reply_mode: <modo>` en
`memory/preferences.md`; si no hay línea válida se usa `reply_mode` de `config/tony.yaml`. En esta
versión el modo solo se guarda: aún no hay salida de voz.

Memoria local (ignorada por git):

- `memory/preferences.md`: preferencias que Jarvis guarda con la tool `remember` (líneas
  `- <texto>`, con secretos enmascarados). Se añade a su prompt en cada mensaje, así que las
  ediciones a mano se aplican al siguiente mensaje.
- `memory/conversations.sqlite`: historial (tabla `messages`). Cada arranque de `tony chat` o de
  la app abre una conversación nueva; a cada mensaje se le envían los 20 mensajes anteriores de
  la conversación actual. Los resultados de Viernes no se guardan como mensajes.

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
`added <nombre> to <fichero>`. Un destino que empieza por `http://` o `https://` crea una
entrada HTTP (`url` y `--header K=V` repetible); cualquier otro, una entrada stdio (`command`,
`--arg` y `--env K=V` repetibles). Mezclar opciones de otro transporte, un par sin `=` o con la
clave vacía, un nombre ya existente, un nombre inválido (`tony`, con `.` o `__`), un agente
inexistente o guardián, o un resultado que no valide terminan con error y dejan el fichero
intacto. Las escrituras se serializan con un bloqueo exclusivo sobre `tool.json.lock` (espera
como máximo 5 s) y sustituyen el fichero de forma atómica (JSON UTF-8 con sangría de 2 espacios).

Los `${VAR}` se escriben tal cual y se resuelven al conectar, desde el entorno o
`config/.env`. Si la clave de un `--header` o `--env` parece un secreto (`token`, `key`,
`secret`, `password`, `passwd`, `authorization`, `pin`) y su valor no usa `${...}`, la entrada
se escribe igualmente y stderr avisa recomendando un `${VAR}` definido en `config/.env`; los
valores nunca se imprimen.

`tony mcp list [--agent <agente>]` conecta cada servidor declarado con las mismas reglas que
una tarea, imprime la tabla `agent server state tools` (`ok` o `error: <motivo enmascarado>`, y
el número de tools) y cierra todas las conexiones. Sale con 0 aunque haya servidores caídos;
un `--agent` inexistente o un `tool.json` inválido (que se nombra en stderr mientras se listan
los demás) dan un código distinto de 0.

### Recarga en caliente

La app de escritorio y `tony chat` vigilan (con `watchfiles`) cada
`agents/<agente>/tool/tool.json`, cada `agents/<agente>/subagents/<sub>/tool/tool.json` y el
`agents/<guard>/policy.yaml`, también los creados después de arrancar; el resto de ficheros
(incluido `tool.json.lock`) se ignora. `tony run` no vigila nada: cada ejecución ya lee los
ficheros al empezar.

- Un cambio válido de `policy.yaml` se aplica a la siguiente llamada a una tool, incluso dentro
  de una tarea en curso. Los `limits` (salvo `confirm_timeout_s`) se aplican desde la siguiente
  tarea y `auth` desde la siguiente sesión.
- Un cambio válido de un `tool.json` se usa en la siguiente tarea o turno; la tarea en curso
  conserva los servidores con los que empezó. Solo se conectan (y se cierran) los servidores
  añadidos o modificados para actualizar su estado; los eliminados aparecen caídos con el motivo
  `removed from tool.json`.
- Un cambio inválido (YAML o JSON roto, error de esquema o fichero borrado) mantiene la última
  configuración válida, publica un evento `error` (origen `reload`) y escribe en stderr
  `tony: warning: <fichero>: <error>`. El siguiente guardado válido se aplica con normalidad.

Las skills y los subagentes no necesitan vigilancia: se leen del disco en cada tarea o turno.

## Desarrollo

```bash
uv run pytest            # offline; omite los tests marcados evals y voice
TONY_EVALS=1 uv run pytest tests/evals   # modelo real (requiere credenciales y npx)
uv run ruff check && uv run ruff format --check
```
