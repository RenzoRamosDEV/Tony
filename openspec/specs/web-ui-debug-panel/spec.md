# web-ui-debug-panel Specification

## Purpose
Define el panel lateral de debug de la web: árbol de tareas con subagentes, tool calls, consumo de tokens y coste con alerta, ruta del log JSONL, eventos de recarga de configuración y exportación del árbol como JSON.

## Requirements

### Requirement: Panel lateral plegable
La UI SHALL mostrar un panel lateral plegable con un botón de alternancia (con `aria-label` y `aria-expanded`); el estado plegado/desplegado SHALL conservarse en el navegador entre recargas y el panel SHALL mostrar la tarea raíz actual o, si no hay ninguna activa, la última terminada de la conversación.

#### Scenario: Plegado persistente
- **GIVEN** el panel plegado por el usuario
- **WHEN** se recarga la página
- **THEN** el panel sigue plegado y el botón tiene `aria-expanded="false"`

#### Scenario: Última tarea
- **GIVEN** la tarea `t-9` terminada y ninguna activa
- **WHEN** se abre el panel
- **THEN** muestra `t-9` con su estado final

### Requirement: Árbol de tareas con estado
El panel SHALL mostrar la tarea raíz y, anidadas, sus subtareas (`subtask.started {task_id, agent}` y eventos con `parent_id`), cada una con `task_id`, agente y estado derivado de los eventos (`queued`, `running`, `waiting_confirmation`, `done`, `failed`, `cancelled`, `timeout`).

#### Scenario: Subtarea anidada
- **WHEN** llegan `task.running` de `t-9` y `subtask.started {task_id: "s-1", agent: "investigador"}`
- **THEN** el árbol muestra `t-9` en `running` con el hijo `s-1 · investigador`

#### Scenario: Estado final del hijo
- **WHEN** llega `subtask.finished {task_id: "s-1", status: "done"}`
- **THEN** el nodo `s-1` muestra `done`

#### Scenario: Esperando confirmación
- **WHEN** llega `task.needs_confirmation` de `t-9`
- **THEN** el nodo `t-9` muestra `waiting_confirmation`

### Requirement: Lista de tool calls
Por cada tarea del árbol el panel SHALL listar sus `tool.call` emparejados con su `tool.result` por orden: tool, `args` formateados (ya redactados por el servidor), duración en ms y error si lo hay; una llamada sin resultado SHALL mostrarse como "en curso".

#### Scenario: Llamada con resultado
- **WHEN** llegan `tool.call {tool: "filesystem.read_file", args: {path: "/n/a.md"}}` y `tool.result {tool: "filesystem.read_file", ok: true, duration_ms: 12, error: null}`
- **THEN** la lista muestra `filesystem.read_file`, `{"path": "/n/a.md"}` y `12 ms`

#### Scenario: Llamada con error
- **WHEN** llega `tool.result {ok: false, error: "timeout"}`
- **THEN** la fila muestra el error con el color de aviso

#### Scenario: Llamada en curso
- **GIVEN** un `tool.call` sin `tool.result`
- **WHEN** se renderiza la lista
- **THEN** la fila muestra "en curso"

### Requirement: Tokens, coste y alerta
El panel SHALL mostrar, a partir de los mensajes `usage`, los tokens de entrada y salida y el coste de la tarea actual, y los acumulados de la conversación (suma de todos los `usage` recibidos, incluidos los de `task_id: null`). Cuando un `usage` traiga `alert: true` SHALL mostrar una alerta visible con color de aviso y el texto "Tarea > 50 k tokens" hasta que empiece otra tarea raíz.

#### Scenario: Contadores
- **WHEN** llegan `usage {task_id: null, input_tokens: 1200, output_tokens: 80}` y `usage {task_id: "t-9", input_tokens: 41200, output_tokens: 9900, cost_usd: 0.31, cumulative_tokens: 51100, alert: true}`
- **THEN** el panel muestra para `t-9` `41 200 / 9 900` y `0,31 USD`, y un acumulado de conversación de `52 380` tokens

#### Scenario: Alerta visible
- **WHEN** llega `usage` con `alert: true`
- **THEN** se muestra "Tarea > 50 k tokens" con `role="alert"` y color de aviso

#### Scenario: Alerta retirada
- **GIVEN** la alerta visible por `t-9`
- **WHEN** llega `task.queued` de `t-10`
- **THEN** la alerta desaparece

### Requirement: Ruta del log y eventos de recarga
El panel SHALL mostrar la ruta del JSONL de cada tarea (`log_path` de `task.queued`) con un botón para copiarla, y una lista de los eventos `config.reloaded`/`config.reload_failed` recibidos con su agente y detalle.

#### Scenario: Ruta del JSONL
- **WHEN** llega `task.queued` con `log_path: "logs/20261028/t-9.jsonl"`
- **THEN** el panel muestra esa ruta y un botón "Copiar ruta"

#### Scenario: Recarga listada
- **WHEN** llega `config.reloaded {agent: "viernes", servers: ["filesystem", "fetch"]}`
- **THEN** el panel lista una entrada con `viernes` y `filesystem, fetch`

### Requirement: Copiar JSON del árbol
El panel SHALL ofrecer un botón "Copiar JSON" que copia al portapapeles el árbol de la tarea actual (tareas, estados, tool calls y `usage`) como JSON legible; si el portapapeles no está disponible SHALL mostrar el JSON en un área de texto seleccionable.

#### Scenario: Copia correcta
- **WHEN** el usuario pulsa "Copiar JSON"
- **THEN** el portapapeles contiene un JSON con `task_id`, `status`, `children`, `tools` y `usage` de la tarea actual y se muestra "Copiado"

#### Scenario: Sin portapapeles
- **GIVEN** el navegador sin API de portapapeles
- **WHEN** el usuario pulsa "Copiar JSON"
- **THEN** aparece un área de texto con el JSON
