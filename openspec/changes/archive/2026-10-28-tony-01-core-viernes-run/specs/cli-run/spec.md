# Spec Delta

## Purpose

Define la interfaz de línea de comandos de Tony para ejecutar una tarea con un agente `worker`, su salida, sus códigos de salida y su ayuda en español.

## ADDED Requirements

### Requirement: Comando `tony run`
El sistema SHALL ofrecer `tony run <agente> "<tarea>" [--json] [--agents-dir PATH] [--config PATH]` que carga la configuración y el agente, construye `TaskRequest {objetivo: tarea, contexto: "", restricciones: []}`, arranca los MCPs del agente, ejecuta la tarea y escribe el log.

#### Scenario: Ejecución correcta
- **GIVEN** el agente `viernes` (rol `worker`) y un runner que devuelve `status: ok`
- **WHEN** se ejecuta `tony run viernes "lista los .md"`
- **THEN** el código de salida es `0`

#### Scenario: Directorio de agentes y configuración alternativos
- **GIVEN** agentes en `/tmp/agentes` y configuración en `/tmp/tony.yaml`
- **WHEN** se ejecuta `tony run viernes "x" --agents-dir /tmp/agentes --config /tmp/tony.yaml`
- **THEN** se cargan el agente y la configuración desde esas rutas

### Requirement: Errores de selección de agente
Si el agente no existe o su rol no es `worker`, el sistema SHALL terminar con código de salida `2` y un mensaje en español, sin ejecutar nada.

#### Scenario: Agente inexistente
- **WHEN** se ejecuta `tony run nadie "x"`
- **THEN** el código de salida es `2` y la salida contiene un mensaje en español que nombra `nadie`

#### Scenario: Agente con rol `front`
- **GIVEN** el agente `jarvis` con `role: front`
- **WHEN** se ejecuta `tony run jarvis "x"`
- **THEN** el código de salida es `2` y el mensaje indica que `jarvis` no es un agente `worker`

#### Scenario: Agente mal formado
- **GIVEN** el agente `roto` cuyo `agent.md` no valida
- **WHEN** se ejecuta `tony run roto "x"`
- **THEN** el código de salida es `2` y el mensaje incluye el error de carga

### Requirement: Salida legible por defecto
Sin `--json`, el sistema SHALL imprimir `resumen`, los `pasos` numerados, los `errores` si los hay, y una línea final `tokens: <in>/<out> · coste: $<X> · log: <ruta>`.

#### Scenario: Resultado con pasos y sin errores
- **GIVEN** un `TaskResult` con `resumen: "Hecho"`, `pasos: ["a", "b"]`, `errores: []`
- **WHEN** se ejecuta `tony run viernes "x"`
- **THEN** la salida contiene `Hecho`, `1. a`, `2. b`, no contiene una sección de errores, y termina con una línea que empieza por `tokens:` e incluye `log: ` seguido de la ruta del JSONL

#### Scenario: Resultado con errores
- **GIVEN** un `TaskResult` con `errores: ["Tool filesystem.write_file no confirmada por el usuario"]`
- **WHEN** se ejecuta `tony run viernes "x"`
- **THEN** la salida contiene ese mensaje de error

### Requirement: Salida JSON
Con `--json`, el sistema SHALL imprimir el `TaskResult` completo como JSON en la salida estándar y nada más en ella.

#### Scenario: Salida JSON
- **GIVEN** un runner que devuelve un `TaskResult` con `status: ok`
- **WHEN** se ejecuta `tony run viernes "x" --json`
- **THEN** la salida estándar se analiza como JSON con las claves `status`, `resumen`, `datos`, `pasos`, `errores`

### Requirement: Código de salida según estado
El código de salida SHALL ser `0` si `status` es `ok` o `partial`, y `1` en cualquier otro caso (`error`, `cancelled`, `timeout`).

#### Scenario: Estado `partial`
- **GIVEN** un runner que devuelve `status: partial`
- **WHEN** termina `tony run`
- **THEN** el código de salida es `0`

#### Scenario: Estado `cancelled`
- **GIVEN** un runner que devuelve `status: cancelled`
- **WHEN** termina `tony run`
- **THEN** el código de salida es `1`

### Requirement: Ayuda y versión en español
`tony --help` y `tony run --help` SHALL documentar cada comando y opción en español, y `tony version` SHALL imprimir la versión del paquete.

#### Scenario: Ayuda de `run`
- **WHEN** se ejecuta `tony run --help`
- **THEN** la salida describe `--json`, `--agents-dir` y `--config` en español

#### Scenario: Versión
- **WHEN** se ejecuta `tony version`
- **THEN** la salida contiene la versión declarada del paquete y el código de salida es `0`
