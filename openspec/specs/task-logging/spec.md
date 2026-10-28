# task-logging Specification

## Purpose
Define el registro persistente de cada tarea ejecutada por Tony: formato de evento, ubicación de los ficheros, orden y durabilidad de la escritura, y redacción de secretos.

## Requirements

### Requirement: Contrato de evento
Cada evento registrado SHALL ser un objeto JSON con `schema_version = 1`, `ts` (ISO-8601 en UTC con sufijo `Z`), `task_id`, `seq` (entero creciente desde 1 dentro de la tarea), `type` y `payload`. El `task_id` SHALL ser un ULID o un `uuid4` en hexadecimal.

#### Scenario: Evento de llamada a tool
- **GIVEN** la tarea `01JB...` emite su tercer evento, `tool.call` de `notion.search` con `{query: "PRs"}`
- **WHEN** se registra
- **THEN** la línea escrita es equivalente a `{"schema_version":1,"ts":"2026-10-28T10:00:01.234Z","task_id":"01JB...","seq":3,"type":"tool.call","payload":{"tool":"notion.search","args":{"query":"PRs"}}}`

#### Scenario: `seq` creciente
- **GIVEN** una tarea que emite `task.started`, `tool.call`, `tool.result`, `task.finished`
- **WHEN** se lee el fichero
- **THEN** los valores de `seq` son `1, 2, 3, 4`

### Requirement: Un fichero JSONL por tarea
El sistema SHALL escribir los eventos en `logs/<YYYYMMDD>/<task_id>.jsonl` (fecha UTC del inicio de la tarea), una línea por evento, abriendo el fichero en modo append y haciendo `flush` tras cada evento.

#### Scenario: Ruta del fichero
- **GIVEN** una tarea iniciada el 28-10-2026 (UTC) con `task_id = abc`
- **WHEN** emite su primer evento
- **THEN** existe `logs/20261028/abc.jsonl` con una línea

#### Scenario: Durabilidad por evento
- **GIVEN** una tarea que emitió dos eventos
- **WHEN** el proceso se interrumpe antes de emitir el tercero
- **THEN** el fichero contiene las dos líneas completas

### Requirement: Redacción de secretos
Antes de escribir, el sistema SHALL sustituir por `***` todo valor presente en `config/.env` y todo valor cuya clave, sin distinguir mayúsculas, sea `authorization`, `api_key` o `token`, en cualquier nivel del `payload`.

#### Scenario: Cabecera Authorization
- **GIVEN** un evento con `payload.headers.Authorization = "Bearer abc"`
- **WHEN** se registra
- **THEN** la línea contiene `"Authorization":"***"` y no contiene `abc`

#### Scenario: Valor de `.env` dentro de args
- **GIVEN** `.env` contiene `NOTION_TOKEN=s3cr3t` y un evento con `payload.args.query = "token s3cr3t"`
- **WHEN** se registra
- **THEN** la línea contiene `token ***` y no contiene `s3cr3t`

#### Scenario: Clave anidada `api_key`
- **GIVEN** un evento con `payload.args.options.API_KEY = "xyz"`
- **WHEN** se registra
- **THEN** el valor de `API_KEY` es `***`
