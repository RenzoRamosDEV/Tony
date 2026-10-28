# Proposal

## Why

Tras la entrega 02, Tony conversa y delega, pero todo lo que Viernes sabe hacer vive en Python o en un `tool.json` editado a mano: no hay forma de añadir conocimiento (skills) ni de descomponer una tarea en subagentes con permisos acotados, no existe un comando para dar de alta un MCP ni para diagnosticar la instalación, cada cambio de `tool.json` exige reiniciar `tony chat`, y no hay manera reproducible de comprobar que el sistema sigue funcionando. Esta entrega cierra esa brecha: se añade un MCP y una skill nuevos sin tocar Python y diez evals pasan con fixtures grabados.

## What Changes

- Nuevo paquete `tony.core.skills`: carga de `agents/<agente>/skills/<nombre>/SKILL.md` (frontmatter `name`, `description` ≤ 200, `trigger`), índice `Skills disponibles` (solo nombre y descripción) en el system prompt del `front` y del `worker`, tool nativa `read_skill(nombre)` que devuelve el cuerpo, e inyección automática del cuerpo como bloque `<skill name="…">…</skill>` cuando el texto del usuario contiene una frase de `trigger` (sin distinguir mayúsculas ni acentos). Una skill inválida se registra como error y no bloquea al agente.
- Nuevo paquete `tony.core.subagents`: `agents/<agente>/subagents/<nombre>/` con la misma estructura que un agente; tool nativa `run_subagent(nombre, objetivo, contexto, restricciones)` del `worker` que ejecuta el subagente como subtarea del orquestador con historial propio; permisos del hijo = intersección con los del padre (`tool.json` ausente o vacío → hereda el catálogo exacto; `confirm` del padre siempre heredado; `mcpServers` nuevos solo si el padre no es subagente); profundidad máxima 1; máximo 2 subagentes concurrentes por tarea; fecha límite y puerta de confirmación compartidas con la tarea padre; eventos del hijo con `task_id` propio y `parent_id`.
- Las tools nativas `read_skill` y `run_subagent`, hasta ahora aceptadas en `tool.json.native` pero ignoradas, pasan a construirse: `read_skill` en el servidor `tony` del `front` y del `worker`; `run_subagent` solo en el `worker` (nunca en un subagente ni en el `front`).
- Nuevos comandos de gestión: `tony mcp add|remove|list` (edición atómica de `tool.json` preservando el resto del fichero, validación por conexión con timeout de 10 s, tabla de estado), `tony agents` y `tony agents show <nombre>` (inventario de agentes y subagentes, `AgentSpec` resuelto en YAML sin secretos), `tony doctor` (diagnóstico `✓/✗` con sugerencia accionable, código de salida 1 si hay algún `✗`) y `tony config validate` (lo mismo sin red ni procesos).
- Recarga en caliente de `agents/**/tool/tool.json` mediante un servicio del core (`ConfigWatcher` sobre `watchfiles`) consumido por `tony chat` (y por el servidor web en la entrega siguiente): se valida la configuración, se arranca una nueva generación de MCPs para las tareas nuevas, las tareas en curso conservan la anterior y esta se cierra cuando ninguna la usa; eventos `config.reloaded {agent, servers}` y `config.reload_failed {agent, error}`. `agent.md` y `tony.yaml` siguen exigiendo reinicio; `tony run` no observa.
- Harness de evals: `evals/tareas.yaml` y `evals/conversaciones.yaml`, marcador `evals` excluido de la suite estándar, ejecución con fixtures grabados (`evals/fixtures/<id>.jsonl`) por defecto y con modelo real solo con `TONY_EVALS=1`, juez `claude-haiku` opcional para conversaciones, grabación de cada ejecución real en `evals/runs/<fecha>/`, y 10 evals incluidos (6 de tareas sobre un MCP de ficheros falso, 4 de conversación).
- Reproducibilidad: `tony replay <ruta.jsonl>` imprime la secuencia de eventos de forma legible y `--to-eval <id>` genera la entrada YAML y el fixture; nunca reejecuta tools.
- Datos incluidos: `agents/viernes/tool/tool.json` declara `native: ["read_skill", "run_subagent"]`; se añaden la skill `agents/viernes/skills/resumen-web/SKILL.md` y el subagente `agents/viernes/subagents/investigador/`.
- Sin cambios **BREAKING**: `tony run`, `tony chat`, los contratos `TaskRequest`/`TaskResult` y el formato de evento JSONL se conservan; los eventos del hijo añaden el campo opcional `parent_id` y aparecen tipos de evento nuevos.

Fuera de alcance (entregas 04–05): canal web, voz, scheduler, hot reload de `agent.md`/`tony.yaml`, panel de debug, resumen automático de memoria.

## Capabilities

### New Capabilities
- `agent-skills`: formato y validación de `SKILL.md`, índice de skills en el prompt, tool nativa `read_skill` y activación automática por `trigger`.
- `subagents`: ejecución de subagentes mediante `run_subagent`, intersección de permisos con el padre, profundidad y concurrencia máximas, fecha límite y confirmación compartidas, eventos y exposición como hijos de la tarea.
- `cli-mcp`: comandos `tony mcp add`, `tony mcp remove` y `tony mcp list` sobre `agents/<agente>/tool/tool.json`.
- `cli-agents`: comandos `tony agents` y `tony agents show <nombre>`.
- `cli-doctor`: comandos `tony doctor` y `tony config validate`, comprobaciones, sugerencias y códigos de salida.
- `config-hot-reload`: observación de `tool.json`, generaciones de MCPs, conservación de la última configuración válida y eventos `config.reloaded`/`config.reload_failed`.
- `evals`: formato de `tareas.yaml` y `conversaciones.yaml`, ejecución con fixtures o con modelo real, juez opcional, grabación de ejecuciones y comando `tony replay`.

### Modified Capabilities
- `agent-loader`: la carpeta del agente incorpora `skills/` y `subagents/`; una skill o un subagente inválidos se registran como error sin bloquear la carga; un subagente no carga sus propios `subagents/` ni expone `run_subagent`.
- `front-agent`: el servidor nativo `tony` del `front` incorpora `read_skill`, y el prompt incluye el índice de skills y los bloques de skills activadas por `trigger`.
- `agent-runner`: el `worker` recibe un servidor nativo `tony` con `read_skill` y `run_subagent` cuando los declara, su system prompt incluye el índice de skills y la petición incorpora los bloques de skills activadas por `trigger`.

## Impact

- Código nuevo: `tony/core/skills/` (modelos, parser, índice, triggers), `tony/core/subagents/` (permisos, lanzador, construcción del hijo), `tony/core/config/watcher.py`, `tony/core/mcp/generations.py`, `tony/core/orchestrator/reload.py`, `tony/core/loader/tooljson.py`, `tony/core/doctor/`, `tony/core/evals/`, `tony/core/logging/replay.py`, `tony/core/runner/oneshot.py`, `tony/apps/cli/{mcp_cli,agents_cli,doctor_cli,replay_cli}.py`, `evals/` (YAML, fixtures, harness pytest), `tests/` (dobles: MCP de ficheros falso, observador de ficheros falso, runner de replay).
- Código modificado: `tony/core/loader/{models,loader}.py` (skills, subagentes, `parent`), `tony/core/runner/{native_tools,claude_sdk,prompt,front_prompt}.py`, `tony/core/orchestrator/{task,orchestrator,ports,worker}.py` (subtareas con `agent`, deadline y puerta compartidos, generaciones), `tony/core/channels/session.py` (`read_skill`, triggers, avisos de recarga), `tony/apps/cli/{main,chat}.py`, `tests/test_architecture.py`, `agents/viernes/tool/tool.json`, `README.md`, `.gitignore` (`evals/runs/`).
- Dependencias: `watchfiles` (ya declarada, sin uso hasta ahora) pasa a usarse; `pyyaml` para los ficheros de evals; ninguna dependencia nueva. `claude_agent_sdk` sigue confinado a los adaptadores del runner (se añade `tony.core.runner.oneshot` para la petición mínima de `doctor` y del juez).
- Sistemas externos: Claude Code CLI autenticado (solo `doctor` sin `--offline`, evals con `TONY_EVALS=1` y la sesión de cierre); `npx` para el MCP `fetch` del cierre; `espeak-ng` y los extras de voz solo se detectan e informan.
- Compatibilidad: `tony run` y `tony chat` conservan su comportamiento; `WorkerFactory` amplía su puerto (adjuntar el anfitrión de subtareas y liberar la generación al terminar) y los dobles de prueba se actualizan en consecuencia.
