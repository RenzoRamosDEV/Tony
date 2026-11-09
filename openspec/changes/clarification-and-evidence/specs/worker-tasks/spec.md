## ADDED Requirements

### Requirement: Sources travel inside datos
A worker MAY return sources as the key `fuentes` (a list of source objects) inside an object `datos`. The four-field result contract `{resumen, datos, pasos, errores}` SHALL stay unchanged: no field is added to the result and a result with any other `datos` shape remains valid.

#### Scenario: Contract unchanged
- **WHEN** a worker returns `datos` `{"correos": 2, "fuentes": [...]}`
- **THEN** the result has exactly the fields `resumen`, `datos`, `pasos` and `errores`

### Requirement: Evidence validation in worker runs
Every worker run, including a subagent run, SHALL pass its result through the source validation of the answer-evidence capability before returning it, and the published task `result` event SHALL carry the validated result.

#### Scenario: Event carries validated sources
- **WHEN** a task result contains one invented source
- **THEN** the `result` event's `result.datos.fuentes` does not contain it
