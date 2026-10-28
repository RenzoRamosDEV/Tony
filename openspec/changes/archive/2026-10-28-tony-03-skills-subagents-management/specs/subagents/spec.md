# Spec Delta

## Purpose

Define cómo un `worker` descompone trabajo en subagentes: la tool nativa `run_subagent`, los permisos efectivos del hijo respecto al padre, los límites de profundidad y concurrencia, y cómo el hijo comparte deadline y confirmación con la tarea padre y aparece como hijo de esta.

## ADDED Requirements

### Requirement: Tool nativa `run_subagent`
Cuando `tool.json.native` del `worker` incluye `run_subagent`, su servidor nativo `tony` SHALL exponer `run_subagent(nombre: str, objetivo: str, contexto: str = "", restricciones: list[str] = []) -> TaskResult`, que ejecuta `subagents/<nombre>/` del agente como subtarea de la tarea en curso, con una sesión de modelo e historial propios, y devuelve su `TaskResult` serializado en JSON. SHALL NOT aplicarse el límite de 20 s de las tools MCP, solo el de la tarea.

#### Scenario: Subagente devuelve su resultado
- **GIVEN** el `worker` `viernes` con el subagente `investigador` y `native: ["run_subagent"]`
- **WHEN** el modelo llama a `run_subagent("investigador", "busca fuentes sobre X")`
- **THEN** se ejecuta el subagente con `TaskRequest {objetivo: "busca fuentes sobre X", contexto: "", restricciones: []}` y el modelo recibe su `TaskResult` como JSON

#### Scenario: Subagente desconocido
- **GIVEN** `viernes` sin subagente `nadie`
- **WHEN** el modelo llama a `run_subagent("nadie", "x")`
- **THEN** recibe un `TaskResult` con `status = "error"` cuyos `errores` nombran `nadie` y listan los subagentes disponibles, sin excepción

#### Scenario: Sin límite de 20 s
- **GIVEN** `tool_timeout_s = 1` y un subagente que tarda 2 s
- **WHEN** el `worker` llama a `run_subagent`
- **THEN** la llamada espera los 2 s y devuelve el resultado sin error de timeout

#### Scenario: El modelo del hijo es el suyo
- **GIVEN** `viernes` con `model: claude-sonnet` y `subagents/investigador/agent.md` con `model: claude-haiku`
- **WHEN** se ejecuta el subagente
- **THEN** la sesión del hijo usa el ID resuelto de `claude-haiku`

### Requirement: Permisos del hijo como intersección con el padre
El catálogo efectivo del subagente SHALL contener solo las tools que permiten a la vez el `allow` del padre y el `allow` del hijo. Si el `tool.json` del hijo falta o está vacío, el hijo SHALL heredar exactamente el catálogo del padre. La lista `confirm` del padre SHALL heredarse siempre y no poder eliminarse; el hijo SHALL poder añadir entradas.

#### Scenario: Tabla de intersección
- **GIVEN** las combinaciones (padre `allow`, hijo `tool.json`): (`["fs.*"]`, ausente); (`["fs.*"]`, `allow: ["fs.read_file", "notion.*"]`); (ausente, `allow: ["fs.read_file"]`) sobre un padre con los servidores `fs` (`read_file`, `write_file`) y `notion` (`search`)
- **WHEN** se calcula el catálogo efectivo del hijo
- **THEN** se obtiene, respectivamente: `fs.read_file` y `fs.write_file`; solo `fs.read_file`; solo `fs.read_file`

#### Scenario: Herencia de confirm
- **GIVEN** padre con `confirm: ["fs.write_file"]` e hijo con `confirm: []`
- **WHEN** el hijo intenta ejecutar `fs.write_file`
- **THEN** se exige confirmación igualmente

#### Scenario: El hijo añade confirm
- **GIVEN** padre con `confirm: []` e hijo con `confirm: ["fs.read_file"]`
- **WHEN** se calcula la política del hijo
- **THEN** `fs.read_file` exige confirmación en el hijo y no en el padre

### Requirement: Servidores MCP nuevos del hijo
Un subagente SHALL poder declarar en `mcpServers` servidores que el padre no declara solo si el padre no es a su vez un subagente; sus tools SHALL pasar igualmente por el `allow` del padre. Un servidor con el mismo nombre que uno del padre SHALL usar la definición del padre.

#### Scenario: Servidor nuevo permitido
- **GIVEN** padre `viernes` (no subagente) sin `allow` e hijo que declara el servidor `fetch`
- **WHEN** se ejecuta el subagente
- **THEN** su catálogo incluye las tools de `fetch` y se conectan solo para esa subtarea

#### Scenario: Servidor nuevo filtrado por el allow del padre
- **GIVEN** padre con `allow: ["fs.*"]` e hijo que declara el servidor `notion`
- **WHEN** se calcula el catálogo efectivo del hijo
- **THEN** ninguna tool de `notion` está disponible

#### Scenario: Servidor nuevo rechazado en un padre subagente
- **GIVEN** un padre que es subagente y un hijo que declara un servidor nuevo
- **WHEN** se calcula la política del hijo
- **THEN** el servidor nuevo se ignora con una advertencia que lo nombra

### Requirement: Profundidad máxima 1
Un subagente SHALL NOT poder llamar a `run_subagent`: la tool SHALL NOT exponerse en su servidor nativo aunque su `tool.json` la declare, y sus propios `subagents/` SHALL NOT cargarse.

#### Scenario: Tool no expuesta al subagente
- **GIVEN** `subagents/investigador/tool/tool.json` con `native: ["run_subagent", "read_skill"]`
- **WHEN** se construye el servidor nativo del subagente
- **THEN** expone `read_skill` y no expone `run_subagent`, y se registra una advertencia

#### Scenario: Subagentes anidados ignorados
- **GIVEN** `subagents/investigador/subagents/otro/`
- **WHEN** se carga `viernes`
- **THEN** `investigador` no tiene subagentes y no se produce error

### Requirement: Máximo 2 subagentes concurrentes por tarea
Una tarea SHALL ejecutar como máximo dos subagentes a la vez; una tercera llamada a `run_subagent` SHALL esperar a que termine una de las anteriores, sin error.

#### Scenario: El tercero espera
- **GIVEN** un `worker` que llama a `run_subagent` tres veces en paralelo con subagentes que tardan 5 s
- **WHEN** han pasado 1 s
- **THEN** hay exactamente dos subtareas en `running` y la tercera no ha empezado; cuando termina una, la tercera arranca

### Requirement: Deadline compartido con la tarea padre
Una subtarea SHALL compartir la fecha límite de su tarea padre (`task_timeout_s` desde que el padre entró en `running`) en lugar de disponer de 300 s propios. Cuando el padre expira o se cancela, sus subtareas en curso SHALL terminar con el mismo estado y motivo.

#### Scenario: El hijo hereda el tiempo restante
- **GIVEN** `task_timeout_s = 10` y un padre que lleva 8 s en `running` cuando lanza un subagente que tarda 5 s
- **WHEN** transcurren 2 s más
- **THEN** la subtarea termina en `timeout` y el padre recibe ese `TaskResult`

#### Scenario: Cancelación en cascada
- **GIVEN** un padre con una subtarea en `running`
- **WHEN** se cancela el padre con motivo `user`
- **THEN** la subtarea pasa a `cancelled`, emite `task.cancelled {reason: "user"}` y no ejecuta ninguna tool más

### Requirement: Puerta de confirmación compartida
Las confirmaciones solicitadas por un subagente SHALL pasar por la misma puerta que las de la tarea padre: SHALL emitirse `task.needs_confirmation` en el flujo de eventos del padre (con el `task_id` del hijo en el payload), SHALL haber como máximo una confirmación visible por conversación y la respuesta SHALL resolverse con el mismo `confirm(confirmation_id, approved)`. Un rechazo SHALL cancelar solo la subtarea con motivo `not_confirmed`.

#### Scenario: Confirmación del hijo visible en el padre
- **GIVEN** la subtarea `s1` del padre `t1` intenta `fs.write_file`
- **WHEN** el proxy del hijo solicita confirmación
- **THEN** el flujo `events("t1")` recibe `task.needs_confirmation {confirmation_id, tool: "fs.write_file", args, task_id: "s1"}` y `s1` pasa a `waiting_confirmation`

#### Scenario: Rechazo cancela solo al hijo
- **GIVEN** `s1` esperando la confirmación `c1`
- **WHEN** llega `confirm("c1", false)`
- **THEN** `s1` termina en `cancelled` con motivo `not_confirmed`, `t1` sigue en `running` y `run_subagent` devuelve el `TaskResult` cancelado

### Requirement: Eventos e identidad del hijo
Cada evento de una subtarea SHALL llevar el `task_id` propio del hijo y el campo `parent_id` con el identificador del padre, tanto en su flujo de eventos como en su fichero JSONL `logs/<fecha>/<task_id>.jsonl`. El orquestador SHALL exponer las subtareas como hijos de la tarea padre y emitir en el flujo del padre `subtask.started {task_id, agent}` y `subtask.finished {task_id, status}`.

#### Scenario: Eventos del hijo
- **GIVEN** la subtarea `s1` del padre `t1`
- **WHEN** se lee su fichero JSONL
- **THEN** cada línea tiene `task_id = "s1"` y `parent_id = "t1"`

#### Scenario: Hijos consultables
- **GIVEN** `t1` lanzó `s1` (`investigador`) y `s2` (`redactor`)
- **WHEN** se consultan los hijos de `t1`
- **THEN** se obtienen `s1` y `s2` con sus agentes y estados, y `events("t1")` contiene `subtask.started {task_id: "s1", agent: "investigador"}` y, al terminar, `subtask.finished {task_id: "s1", status: "done"}`

### Requirement: `run_subagent` fuera del orquestador
Cuando el `worker` se ejecuta sin orquestador (`tony run`), `run_subagent` SHALL devolver un `TaskResult` con `status = "error"` que explique que los subagentes solo están disponibles en `tony chat` y en el servidor web, sin ejecutar nada.

#### Scenario: tony run con subagentes declarados
- **GIVEN** `tony run viernes "x"` y un modelo que llama a `run_subagent("investigador", "y")`
- **WHEN** se procesa la llamada
- **THEN** el modelo recibe `{status: "error", errores: ["run_subagent solo está disponible en tony chat y en el servidor web"], ...}` y no se crea ninguna subtarea
