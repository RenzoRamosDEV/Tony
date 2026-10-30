# Proposal

## Why

Jarvis (front) y Viernes (worker) solo pueden hablar con el modelo a través del Claude Agent SDK. Para usar Codex CLI o cualquier proveedor con clave de API (OpenAI, Claude por clave, Gemini, etc.) hace falta un motor intercambiable por agente, sin tocar la arquitectura de ejecución, confirmación y registro ya existente.

## What Changes

- Nuevo campo `engine` en el frontmatter de `agent.md` (opcional, por defecto `claude_sdk`) que selecciona el motor de lenguaje de ese agente, resuelto contra un mapa `engines:` de `tony.yaml`.
- Nuevo motor `codex_cli`: ejecuta `codex exec`/`codex exec resume` como `AgentRunner` (uno por tarea) y `ConversationRunner` (sesión por `session_id` de Codex), expone el mismo `ToolCatalog` a través de una pasarela MCP stdio propia (`tony mcp-gateway`) y usa `--output-schema` para la salida estructurada.
- Nuevo motor `litellm`: ejecuta un bucle de llamada a herramientas en proceso contra `litellm.acompletion`, traduciendo el `ToolCatalog` a tools estilo OpenAI y los resultados de MCP a mensajes `role: "tool"`, con salida estructurada vía `response_format` y un fallback de texto cuando el proveedor no la soporta.
- Comandos `tony engine set <agente> <perfil>` y `tony engine list` para cambiar y listar el motor activo por agente (edición atómica de `agent.md`, mismo patrón que `tony mcp add`).
- `tony doctor`/`tony config validate` ganan comprobaciones por motor: presencia y autenticación de `codex`, y presencia de la clave de proveedor que exige el modelo configurado del perfil `litellm`.
- **BREAKING**: ninguno. Sin `engine` declarado, el comportamiento y las especificaciones existentes no cambian (motor por defecto `claude_sdk`).
- Fuera de alcance: cambiar el motor por defecto, selector de motor desde el chat web, fallback automático entre motores. El streaming de voz (`on_speech` parcial) solo funciona con `claude_sdk`; los otros motores degradan a "hablar tras la respuesta completa", documentado como limitación explícita.

## Capabilities

### New Capabilities
- `engine-selection`: esquema de configuración (`engines:` global, `engine:` por agente), resolución de alias de modelo por motor, comandos `tony engine set/list` y comprobaciones de `tony doctor` por motor.
- `codex-engine`: ejecución de tareas y conversación del front/worker usando Codex CLI como motor, incluida la pasarela MCP que expone el mismo catálogo de tools y la salida estructurada vía esquema JSON.
- `litellm-engine`: ejecución de tareas y conversación usando cualquier proveedor compatible con LiteLLM vía clave de API, con bucle de herramientas propio sobre la misma barrera de ejecución y salida estructurada con fallback de texto.

### Modified Capabilities
- `agent-loader`: `agent.md` acepta el nuevo campo opcional `engine` y lo valida contra los perfiles declarados en `engines:`.
- `agent-runner`: la ejecución de una tarea del worker ya no asume un único motor; el motor efectivo del agente decide qué implementación de `AgentRunner` se usa, manteniendo intactos el contrato `TaskRequest`/`TaskResult`, la barrera de proxies MCP y los eventos de progreso.
- `front-agent`: la sesión conversacional del front usa la implementación de `ConversationRunner` del motor efectivo del agente, manteniendo intacto el contrato de turno, el aislamiento del worker y los avisos de recarga.
- `cli-doctor`: `tony doctor` y `tony config validate` añaden comprobaciones específicas de los motores `codex_cli` y `litellm` cuando algún agente los usa.

## Impact

- Código: `tony/core/runner/ports.py`, `tony/core/runner/conversation.py`, `tony/core/orchestrator/worker.py` (factoría de motor), `tony/core/loader/models.py` y `frontmatter.py` (campo `engine`), `tony/core/config/settings.py` (`engines:`), `tony/apps/cli/doctor_cli.py`, `tony/core/doctor/checks.py`, nuevo `tony/apps/cli/engine_cli.py`.
- Dependencias nuevas: `litellm` (PyPI). Codex CLI es un binario externo ya instalado por el usuario, igual que `claude` CLI.
- Config: `config/tony.yaml` gana `engines:`; `config/.env` gana claves de proveedor opcionales (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) cuando se usa un perfil `litellm`.
- Sin impacto en instalaciones existentes: ningún agente declara `engine` hoy, así que todos siguen en `claude_sdk` sin cambios de comportamiento.
