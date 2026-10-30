# Tasks

## 1. Esquema de configuración y carga de agentes (`engine-selection`, `agent-loader`)

- [x] 1.1 Escribir tests que fallen para `EngineProfile`/`engines` en `tony/core/config/settings.py` (perfil `claude_sdk` implícito siempre presente; perfil `litellm` sin `model` rechazado) y verificar que fallan antes de implementar
- [x] 1.2 Implementar `EngineProfile` y `TonySettings.engines`; verificar que los tests de 1.1 pasan
- [x] 1.3 Escribir tests que fallen para el campo `engine` de `AgentSpec`/`agent.md` (ausente → `claude_sdk`; perfil desconocido → error con perfiles disponibles) en `tony/core/loader/models.py` y `frontmatter.py`/`loader.py`, y verificar que fallan
- [x] 1.4 Implementar la validación de `engine` contra `engines` (incluyendo el perfil implícito `claude_sdk`); verificar que los tests de 1.3 pasan y que la suite existente de `agent-loader` sigue en verde
- [x] 1.5 Ejecutar `uv run pytest -q tests -k "settings or loader"` y confirmar 0 fallos; revisar mutantes del diff de 1.1-1.4 con el runner de mutación del proyecto, límite 3 min, y justificar cualquier mutante superviviente por debajo del 95%

## 2. Puertos de motor y factoría genérica (`agent-runner`, `front-agent`, sin motores nuevos aún)

- [x] 2.1 Escribir un test que falle demostrando que la tarea/conversación del `claude_sdk` actual sigue produciendo el mismo `TaskResult`/`FrontReply` tras introducir un punto de selección de motor (no debe cambiar comportamiento observable), y verificar que falla contra la factoría actual sin el punto de selección
- [x] 2.2 Implementar `build_runner_factory(settings, spec)` y `build_conversation(settings, spec)` en `tony/core/runner/` que, para `engine` resuelto a `type: claude_sdk`, devuelven exactamente `default_worker_runner_factory`/`ClaudeSdkConversation`; conectar `SdkWorkerFactory` (`tony/core/orchestrator/worker.py`) y el arranque del front a ese punto de selección; verificar que el test de 2.1 pasa y que toda la suite existente de `agent-runner`/`front-agent` sigue en verde sin cambios
- [x] 2.3 Ejecutar `uv run pytest -q tests -k "runner or front_agent or worker"` y confirmar 0 fallos

## 3. Barrera de tools reutilizable fuera de proceso (`codex-engine`, base)

- [ ] 3.1 Escribir tests que fallen para una versión transporte-agnóstica de `ToolProxyFactory`/`ToolCaller` que pueda servir tanto un `McpSdkServerConfig` en proceso como un servidor MCP stdio real, preservando el orden cancelación → `allow` → confirmación → timeout → log
- [ ] 3.2 Refactorizar `tony/core/runner/proxy.py` para separar la lógica de la barrera del transporte en proceso; verificar que los tests de 3.1 pasan y que la suite de `claude_sdk` (que sigue usando el transporte en proceso) no cambia de comportamiento
- [ ] 3.3 Añadir un fake binario `codex` de pruebas (script en `tests/fakes/fake_codex.py` o similar, sin red) que emula `codex exec`/`codex exec resume --json --output-schema` leyendo un guion de respuestas fijado por el test, para usarlo en 4.x sin invocar el `codex` real

## 4. Motor `codex_cli` (`codex-engine`)

- [ ] 4.1 Escribir tests que fallen para `CodexCliRunner` (`AgentRunner`): invoca el fake `codex exec --json --output-schema`, parsea el `TaskResult` de la salida estructurada, y produce `status: "error"` si la salida no cumple el esquema
- [ ] 4.2 Implementar `CodexCliRunner` usando el fake de 3.3; verificar que los tests de 4.1 pasan
- [ ] 4.3 Escribir tests que fallen para la pasarela MCP (`tony mcp-gateway`): expone el mismo `ToolCatalog` que el proxy en proceso, aplica la misma barrera (reutilizando 3.2) y responde por stdio a un cliente MCP de prueba
- [ ] 4.4 Implementar el comando interno `tony mcp-gateway` y el cableado `-c mcp_servers.tony.command=...`/`args=[...]` en `CodexCliRunner`; verificar que los tests de 4.3 pasan
- [ ] 4.5 Escribir tests que fallen para `CodexCliConversation` (`ConversationRunner`): primer turno abre sesión y captura `session_id`; turno siguiente usa `codex exec resume <session_id>`; sin streaming parcial de voz (`on_speech` solo se llama una vez, al final)
- [ ] 4.6 Implementar `CodexCliConversation` sobre el fake `codex`; verificar que los tests de 4.5 pasan
- [ ] 4.7 Conectar `codex_cli` en `build_runner_factory`/`build_conversation` (de 2.2) para `engine` resuelto a `type: codex_cli`; verificar con un test de integración que un agente con `engine: codex_cli` construye `CodexCliRunner`/`CodexCliConversation` y uno sin `engine` sigue construyendo los de `claude_sdk`
- [ ] 4.8 Ejecutar `uv run pytest -q -m "not codex and not voice"` y confirmar que la suite estándar pasa sin tocar red ni el binario `codex` real; marcar los tests que sí usan el `codex` real con `@pytest.mark.codex` y excluirlos del run por defecto en `pyproject.toml` (igual que `voice`)

## 5. Motor `litellm` (`litellm-engine`)

- [ ] 5.1 Añadir `litellm` como dependencia opcional en `pyproject.toml` (grupo `litellm` o dependencia directa, a decidir según si siempre se instala) y verificar `uv sync` resuelve sin conflicto con `openai`/`anthropic` ya usados indirectamente
- [ ] 5.2 Escribir un fake cliente LiteLLM (`tests/fakes/fake_litellm.py`, sin red) que sustituye `litellm.acompletion` por una secuencia de respuestas programada (con y sin `tool_calls`, con y sin soporte de `response_format`)
- [ ] 5.3 Escribir tests que fallen para `LiteLlmRunner`/`LiteLlmConversation`: bucle de tool-calls hasta una respuesta final, ejecución de cada tool a través de la misma barrera de 3.2, parada en `max_steps` con `status: "error"`
- [ ] 5.4 Implementar `LiteLlmRunner`/`LiteLlmConversation` sobre el fake de 5.2; verificar que los tests de 5.3 pasan
- [ ] 5.5 Escribir tests que fallen para la salida estructurada con fallback: `response_format` soportado valida contra el esquema; no soportado cae a extracción de JSON del texto; sin JSON extraíble devuelve el texto completo con `status: "ok"`
- [ ] 5.6 Implementar la lógica de fallback de salida estructurada; verificar que los tests de 5.5 pasan
- [ ] 5.7 Escribir un test que falle para la resolución de clave de proveedor ausente (`status: "error"` nombrando la variable esperada antes de llamar al proveedor) y verificar que falla
- [ ] 5.8 Implementar la comprobación de clave antes de la primera llamada; verificar que el test de 5.7 pasa
- [ ] 5.9 Conectar `litellm` en `build_runner_factory`/`build_conversation` para `engine` resuelto a `type: litellm`; verificar con un test de integración análogo al de 4.7
- [ ] 5.10 Ejecutar `uv run pytest -q -m "not litellm and not codex and not voice"` y confirmar que la suite estándar pasa sin llamadas reales a ningún proveedor; marcar los tests que sí llaman a un proveedor real con `@pytest.mark.litellm` y excluirlos del run por defecto en `pyproject.toml`

## 6. CLI `tony engine` (`engine-selection`)

- [ ] 6.1 Escribir tests que fallen para `tony engine set <agente> <perfil>`: edición atómica de `engine` en `agent.md` (perfil válido), fallo sin escritura si el perfil no existe en `engines`
- [ ] 6.2 Implementar `tony/apps/cli/engine_cli.py` con `set`, reutilizando el patrón de edición atómica de `tony/core/loader/tooljson.py`; verificar que los tests de 6.1 pasan
- [ ] 6.3 Escribir tests que fallen para `tony engine list`: muestra cada agente/subagente con su motor efectivo y el tipo de perfil resuelto
- [ ] 6.4 Implementar `list` reutilizando `load_all` y `render_table`; verificar que los tests de 6.3 pasan
- [ ] 6.5 Registrar `engine_cli.app` en `tony/apps/cli/main.py` y escribir un test de ayuda en español (`tony engine --help`, `tony engine set --help`, `tony engine list --help`); verificar que pasa

## 7. Comprobaciones de `tony doctor` (`cli-doctor`)

- [ ] 7.1 Escribir tests que fallen en `tony/core/doctor/checks.py` para la comprobación `codex_cli`: binario presente/autenticado → `✓`; ausente → `✗` con sugerencia; omitida con `--offline` igual que `claude`
- [ ] 7.2 Implementar la comprobación `codex_cli`; verificar que los tests de 7.1 pasan
- [ ] 7.3 Escribir tests que fallen para la comprobación `litellm`: variable de clave presente → `✓`; ausente → `✗` nombrando la variable
- [ ] 7.4 Implementar la comprobación `litellm`; verificar que los tests de 7.3 pasan
- [ ] 7.5 Escribir un test que falle confirmando que, sin ningún agente usando motores alternativos, no aparece ninguna línea de comprobación de `codex`/`litellm`; verificar que pasa tras 7.2/7.4
- [ ] 7.6 Extender `tony config validate` para incluir la comprobación `litellm` (no requiere red ni proceso) y excluir la de `codex_cli` (requiere proceso), con un test que lo confirme
- [ ] 7.7 Ejecutar `uv run pytest -q -m "not codex and not litellm and not voice"` y confirmar que toda la suite de `cli-doctor` pasa

## 8. Verificación final

- [ ] 8.1 Ejecutar `uv run pytest -q` (suite estándar completa, sin red ni llamadas reales a `codex`/proveedores) y confirmar 0 fallos
- [ ] 8.2 Ejecutar `ruff check .` y `ruff format --check .` y confirmar 0 incidencias
- [ ] 8.3 Comprobación manual real de `codex_cli`: ejecutar `tony engine set viernes codex_cli` con un perfil `codex_cli` declarado en `tony.yaml`, lanzar `tony run viernes "<tarea de prueba que use una tool del catálogo>"` contra el `codex` real instalado, y verificar en el log JSONL de la tarea que la llamada a la tool pasó por la pasarela (eventos `tool.call`/`tool.result`) y que el `TaskResult` final es coherente; verificar además, inspeccionando el comando real lanzado (p. ej. con `ps`/logging de depuración), que nunca incluye `--dangerously-bypass-approvals-and-sandbox` ni `--approve-for-me` (política no negociable del usuario: lectura libre, confirmación de Tony para toda escritura/ejecución); si el `codex` real pide su propia aprobación para una tool de solo lectura pese al `-s read-only`, documentar el comportamiento exacto observado en el design.md de esta entrega en vez de añadir el flag prohibido
- [ ] 8.4 Comprobación manual real de `litellm`: comprobar primero si `OPENAI_API_KEY` (u otra clave de proveedor) está definida en el entorno o en `config/.env`; si lo está, declarar un perfil `litellm` con un modelo de ese proveedor, ejecutar `tony engine set viernes <perfil>` y `tony run viernes "<tarea de prueba>"` con la clave real, y verificar el `TaskResult` y el log JSONL; si no hay ninguna clave disponible en este entorno, documentar en el informe de la tarea que este paso requiere que el usuario aporte una clave y se omite sin fabricar una
- [ ] 8.5 Ejecutar `tony doctor` con al menos un agente en `codex_cli` y otro en un perfil `litellm` (o el mismo agente en ambos casos de prueba) y verificar que aparecen las líneas `✓`/`✗` de ambos motores descritas en la especificación `cli-doctor`
- [ ] 8.6 Crear un commit con Conventional Commits en la rama `feat/pluggable-engines` (por ejemplo `feat(engines): add pluggable claude_sdk/codex_cli/litellm engines`), sin trailer `Co-Authored-By` ni ninguna atribución a un asistente de IA, y verificar con `git log -1` que el mensaje y el autor son correctos

## Workflow follow-up

- Archivar el change (`openspec archive tony-08-pluggable-engines`) una vez completada la implementación y revisada según el proceso del proyecto.
- Verificar el resultado archivado (`openspec status` y que las specs principales de `engine-selection`, `codex-engine`, `litellm-engine`, `agent-loader`, `agent-runner`, `front-agent` y `cli-doctor` quedan actualizadas en `openspec/specs/`).
