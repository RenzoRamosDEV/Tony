# Spec Delta

## MODIFIED Requirements

### Requirement: Proxies MCP como única barrera de ejecución
Por cada servidor MCP del catálogo, el agente SHALL ver un servidor MCP en proceso con el mismo nombre cuyas tools son proxies con el nombre, descripción y esquema de entrada originales. Cada proxy SHALL aplicar en orden: comprobación de cancelación de la tarea → comprobación de `allow` → confirmación si procede → ejecución con timeout → registro en el log. Una tarea cancelada SHALL NOT ejecutar ninguna tool más.

#### Scenario: Nombre visible para el modelo
- **GIVEN** el catálogo contiene `fs.read_file`
- **WHEN** se construyen los servidores en proceso
- **THEN** el modelo ve la tool `mcp__fs__read_file` con la descripción y el esquema de entrada de `read_file`

#### Scenario: Llamada a través del proxy
- **GIVEN** el modelo invoca `mcp__fake__echo` con `{text: "hola"}`
- **WHEN** el proxy la procesa
- **THEN** se emite `tool.call`, se ejecuta `fake.echo` en el servidor real, se emite `tool.result` con `ok = true` y el modelo recibe `hola`

#### Scenario: Barrera de cancelación
- **GIVEN** la tarea ya está marcada como cancelada
- **WHEN** el modelo invoca `mcp__fake__echo`
- **THEN** el proxy devuelve el error `Tarea cancelada` sin llamar al servidor, sin solicitar confirmación y con `tool.result {ok: false}` en el log

### Requirement: Timeout y errores de tarea
Si la tarea supera `limits.task_timeout_s` (300 s) desde su inicio, incluyendo la conexión del motor y las esperas de confirmación, el `TaskResult` SHALL tener `status = "timeout"`. Una cancelación externa SHALL interrumpir el motor y producir `status = "cancelled"` con el motivo recibido en `errores`. Cualquier excepción del motor SHALL producir `status = "error"` con el mensaje en `errores`, sin trazas para el usuario.

#### Scenario: Timeout de tarea
- **GIVEN** `task_timeout_s = 1` y un agente que no termina
- **WHEN** transcurre 1 s
- **THEN** la ejecución se interrumpe y el `TaskResult` tiene `status = "timeout"` y `task.finished.status = timeout`

#### Scenario: Timeout durante la conexión
- **GIVEN** `task_timeout_s = 0.2` y un motor cuya conexión tarda 2 s
- **WHEN** transcurren 0,2 s
- **THEN** el `TaskResult` tiene `status = "timeout"` sin esperar a que termine la conexión

#### Scenario: Cancelación externa
- **GIVEN** una ejecución en curso
- **WHEN** se cancela desde fuera con motivo `user`
- **THEN** se llama a la interrupción del motor, el `TaskResult` tiene `status = "cancelled"`, `errores` contiene `cancelada por el usuario` y `task.finished.status = cancelled`

#### Scenario: Excepción del motor
- **GIVEN** el motor de ejecución lanza una excepción `connection refused`
- **WHEN** termina la ejecución
- **THEN** el `TaskResult` tiene `status = "error"` y `errores` contiene `connection refused`, y la salida al usuario no contiene traza de pila
