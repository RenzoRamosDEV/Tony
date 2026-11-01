# Tony

Asistente personal local con tres agentes de rol fijo: Jarvis (`front`), Viernes (`worker`) y
Edith (`guard`). Esta fase entrega el núcleo y permite ejecutar a Viernes desde la CLI.

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

Opcional y fuera de git. Contiene los secretos (`NOMBRE=valor`); el entorno del proceso tiene
prioridad. Los valores solo llegan a los servidores MCP mediante marcadores `${NOMBRE}` en
`tool.json`, que se resuelven al arrancar cada servidor. Cualquier valor resuelto se sustituye
por `***` en los resultados de tools, el log de tareas y la salida de la CLI. Plantilla:
`config/.env.example`.

## Agentes: `agents/<nombre>/`

```
agents/viernes/
├── agent.md          # frontmatter YAML + prompt de sistema en Markdown
└── tool/tool.json    # servidores MCP y tools nativas
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

## Uso

```bash
uv run tony run --help
uv run tony run viernes "Lista mis notas"
```

`tony run <agente> "<tarea>"` ejecuta un agente `worker` con la tarea como `objetivo` e imprime
en stdout un único objeto JSON `{resumen, datos, pasos, errores}`. Sale con código 0 si
`errores` está vacío, 1 si el resultado trae errores y 2 si la definición del agente o la tarea
no son válidas (el error, con fichero y campo, va a stderr).

Límites: 10 s de conexión por servidor MCP, 20 s por llamada a tool y 300 s por tarea. Cada
tarea deja su registro en `logs/tasks/<task_id>.jsonl` y el stderr de cada servidor stdio en
`logs/mcp/<servidor>.log`.

## Desarrollo

```bash
uv run pytest            # offline; omite los tests marcados evals y voice
TONY_EVALS=1 uv run pytest tests/evals   # modelo real (requiere credenciales y npx)
uv run ruff check && uv run ruff format --check
```
