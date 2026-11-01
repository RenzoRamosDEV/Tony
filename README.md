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
`persona.tone` y `voice.tts` (`kokoro/<voz>`). El cuerpo es el prompt de sistema y no puede
estar vacío.

`tool/tool.json`:

```json
{
  "mcpServers": {
    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "${HOME}/notas"]},
    "remote": {"url": "https://example.test/mcp", "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"}}
  },
  "native": []
}
```

Cada servidor define `command` (stdio, con `args` y `env` opcionales) o `url` (HTTP streamable,
con `headers` opcionales), nunca ambos. Las tools se identifican como `<servidor>.<tool>`; el
nombre de servidor `tony` está reservado para las tools nativas (`tony.<nombre>`). Las claves
`allow` y `confirm` se rechazan: los permisos pertenecen a `agents/edith/policy.yaml`.

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

## Desarrollo

```bash
uv run pytest            # offline; omite los tests marcados evals y voice
TONY_EVALS=1 uv run pytest tests/evals   # modelo real (requiere credenciales y npx)
uv run ruff check && uv run ruff format --check
```
