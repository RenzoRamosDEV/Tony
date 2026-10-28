# evals Specification

## Purpose
Define el harness de evaluación de Tony: el formato de los evals de tareas y de conversación, su ejecución con fixtures grabados o con modelo real, el juez opcional, la grabación de ejecuciones y el comando `tony replay` para inspeccionar y convertir logs en evals.

## Requirements

### Requirement: Formato de `evals/tareas.yaml`
`evals/tareas.yaml` SHALL ser una lista de entradas `{id, agent, objetivo, contexto, restricciones, expect}` donde `expect` acepta `status`, `tools_called_any` (lista), `tools_called_all` (lista) y `resumen_contains` (lista), todas opcionales salvo `status`. Un `id` duplicado o una entrada sin `id`, `agent` u `objetivo` SHALL rechazarse al cargar.

#### Scenario: Entrada válida
- **GIVEN** la entrada `{id: fs-list-md, agent: viernes, objetivo: "lista los .md de notas", contexto: "", restricciones: [], expect: {status: ok, tools_called_any: ["filesystem.list_directory"], resumen_contains: ["md"]}}`
- **WHEN** se carga el fichero
- **THEN** se obtiene un eval de tarea con esos valores y `tools_called_all` vacío

#### Scenario: Id duplicado
- **GIVEN** dos entradas con `id: fs-list-md`
- **WHEN** se carga el fichero
- **THEN** la carga falla con un error que nombra `fs-list-md`

### Requirement: Formato de `evals/conversaciones.yaml`
`evals/conversaciones.yaml` SHALL ser una lista de entradas `{id, turns: [{user, expect: {delegates, reply_contains, judge}}]}` donde `delegates` es booleano, `reply_contains` una lista opcional y `judge` un criterio en lenguaje natural opcional.

#### Scenario: Conversación válida
- **GIVEN** la entrada `{id: hora, turns: [{user: "¿qué hora es?", expect: {delegates: false, reply_contains: [":"], judge: "Responde la hora sin inventar datos"}}]}`
- **WHEN** se carga el fichero
- **THEN** se obtiene un eval de conversación con un turno cuyo `delegates` es `false`

### Requirement: Ejecución con fixtures o con modelo real
`uv run pytest evals/ -m evals` SHALL ejecutar cada eval. Sin `TONY_EVALS=1`, cada tarea SHALL ejecutarse con un runner que reproduce `evals/fixtures/<id>.jsonl` y cada conversación con un runner conversacional que reproduce su fixture, sin red ni modelo. Con `TONY_EVALS=1` SHALL usarse el runner real. `uv run pytest` sin argumentos SHALL NOT ejecutar los evals.

#### Scenario: Fixtures en verde sin red
- **GIVEN** `TONY_EVALS` sin definir y los 10 fixtures incluidos
- **WHEN** se ejecuta `uv run pytest evals/ -m evals`
- **THEN** pasan 10 evals sin arrancar ningún modelo ni conexión de red

#### Scenario: Fixture ausente
- **GIVEN** `TONY_EVALS` sin definir y un eval `x` sin `evals/fixtures/x.jsonl`
- **WHEN** se ejecuta su prueba
- **THEN** falla con un mensaje que nombra el fixture esperado y sugiere `TONY_EVALS=1` y `tony replay --to-eval`

#### Scenario: Excluidos de la suite estándar
- **WHEN** se ejecuta `uv run pytest`
- **THEN** no se recoge ninguna prueba de `evals/`

### Requirement: Expectativas de una tarea
Un eval de tarea SHALL pasar solo si `TaskResult.status` coincide con `expect.status`, alguna tool de `tools_called_any` aparece en los eventos `tool.call`, todas las de `tools_called_all` aparecen, y cada cadena de `resumen_contains` aparece en `resumen` (sin distinguir mayúsculas). El mensaje de fallo SHALL nombrar cada expectativa incumplida.

#### Scenario: Tool esperada no llamada
- **GIVEN** `expect.tools_called_all: ["filesystem.read_file"]` y un fixture sin `tool.call` de esa tool
- **WHEN** se evalúa
- **THEN** la prueba falla y el mensaje contiene `filesystem.read_file`

#### Scenario: Todas las expectativas cumplidas
- **GIVEN** un fixture con `status: ok`, `tool.call` de `filesystem.list_directory` y `resumen` `Hay 3 ficheros .md`
- **WHEN** se evalúa con `expect: {status: ok, tools_called_any: ["filesystem.list_directory"], resumen_contains: ["ficheros .md"]}`
- **THEN** la prueba pasa

### Requirement: Expectativas de una conversación y juez
Un turno de conversación SHALL pasar solo si la presencia de `task.queued` coincide con `delegates` y cada cadena de `reply_contains` aparece en `display_text`. Con `TONY_EVALS=1` y `judge` definido, el juez SHALL enviar al modelo `claude-haiku` un prompt fijo con el criterio y la respuesta y SHALL obtener `{pass: bool, reason: str}`; `pass = false` SHALL hacer fallar la prueba mostrando `reason`. Sin `TONY_EVALS=1` el juez SHALL omitirse.

#### Scenario: Delegación esperada
- **GIVEN** un turno con `delegates: true` cuyo fixture no delega
- **WHEN** se evalúa
- **THEN** la prueba falla indicando que se esperaba una delegación

#### Scenario: Juez omitido sin modelo
- **GIVEN** `TONY_EVALS` sin definir y un turno con `judge`
- **WHEN** se evalúa
- **THEN** no se realiza ninguna llamada al modelo y la prueba se decide solo por `delegates` y `reply_contains`

#### Scenario: Juez con modelo
- **GIVEN** `TONY_EVALS=1` y un juez que responde `{pass: false, reason: "inventa la hora"}`
- **WHEN** se evalúa
- **THEN** la prueba falla y el mensaje contiene `inventa la hora`

### Requirement: Grabación de ejecuciones reales
Cada ejecución con `TONY_EVALS=1` SHALL escribir el JSONL de la tarea (o de la conversación) en `evals/runs/<YYYYMMDD>/<id>.jsonl`, terminando con el evento `task.result`, de modo que pueda convertirse en fixture. `evals/runs/` SHALL estar ignorado por git.

#### Scenario: Run grabado
- **GIVEN** `TONY_EVALS=1` y el eval `fs-list-md`
- **WHEN** termina su ejecución
- **THEN** existe `evals/runs/<fecha>/fs-list-md.jsonl` cuya última línea es `task.result`

### Requirement: Evals incluidos
El repositorio SHALL incluir 10 evals con sus fixtures: 6 de tareas sobre un servidor MCP de ficheros falso en proceso (listar, leer, buscar, escribir con confirmación aprobada, escritura rechazada que termina en `cancelled`, y tool fallida que termina en `partial` o `error`) y 4 de conversación (saludo sin delegar, hora sin delegar, listado de notas que delega, preferencia recordada sin delegar).

#### Scenario: Diez evals
- **WHEN** se cargan `evals/tareas.yaml` y `evals/conversaciones.yaml`
- **THEN** hay 6 evals de tareas y 4 de conversación, y cada `id` tiene su `evals/fixtures/<id>.jsonl`

### Requirement: Comando `tony replay`
`tony replay <ruta.jsonl>` SHALL imprimir la secuencia de eventos de forma legible: una línea por evento con `seq`, hora y tipo, y para `tool.call` la tool y sus argumentos, para `tool.result` el resultado (`ok`/error y duración), para `task.finished` los tokens y el coste, y para `task.result` el estado y el resumen. SHALL NOT ejecutar ninguna tool ni conectar a ningún servidor. Un fichero inexistente o con una línea no JSON SHALL terminar con código `1`.

#### Scenario: Secuencia legible
- **GIVEN** un JSONL con `task.started`, `tool.call {tool: "fake.echo", args: {text: "hola"}}`, `tool.result {ok: true, duration_ms: 3}`, `task.finished {usage: {input_tokens: 10, output_tokens: 5, total_cost_usd: 0.01}}` y `task.result {result: {status: "ok", resumen: "Hecho"}}`
- **WHEN** se ejecuta `tony replay <ruta>`
- **THEN** la salida contiene `fake.echo`, `hola`, `ok`, `3 ms`, `10/5`, `0.01`, `status: ok` y `Hecho`, y no se arranca ningún servidor

#### Scenario: Fichero inválido
- **WHEN** se ejecuta `tony replay <ruta>` sobre un fichero con una línea que no es JSON
- **THEN** termina con código `1` y un mensaje que nombra el número de línea

### Requirement: Conversión a eval con `--to-eval`
`tony replay <ruta.jsonl> --to-eval <id>` SHALL escribir `evals/fixtures/<id>.jsonl` con los eventos del fichero y SHALL imprimir en la salida estándar una entrada YAML de `tareas.yaml` con `id`, `agent`, `objetivo`, `contexto`, `restricciones` tomados de los eventos y `expect` con el `status` observado y `tools_called_all` con las tools llamadas. Un fixture existente SHALL NOT sobrescribirse salvo con `--force`.

#### Scenario: Fixture y entrada generados
- **GIVEN** un JSONL de `viernes` con `tool.call` de `filesystem.list_directory` y `task.result {status: "ok"}`
- **WHEN** se ejecuta `tony replay <ruta> --to-eval fs-list-md`
- **THEN** existe `evals/fixtures/fs-list-md.jsonl` con las mismas líneas y la salida contiene `id: fs-list-md`, `agent: viernes`, `status: ok` y `filesystem.list_directory`

#### Scenario: Fixture existente
- **GIVEN** `evals/fixtures/fs-list-md.jsonl` existe
- **WHEN** se ejecuta `tony replay <ruta> --to-eval fs-list-md`
- **THEN** termina con código `1`, nombra el fichero y sugiere `--force`, y el fixture no cambia
