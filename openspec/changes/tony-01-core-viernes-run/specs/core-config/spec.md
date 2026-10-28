# Spec Delta

## Purpose

Define cómo Tony carga y valida su configuración global (`config/tony.yaml` y `config/.env`), qué valores por defecto aplica y qué errores devuelve ante configuración inválida.

## ADDED Requirements

### Requirement: Configuración con valores por defecto
El sistema SHALL cargar `config/tony.yaml` en una estructura de configuración tipada con los campos `front`, `worker`, `reply_mode`, `models`, `voice`, `channels`, `web` y `limits`, y SHALL aplicar un valor por defecto a todo campo ausente.

#### Scenario: Fichero de configuración ausente
- **GIVEN** no existe `config/tony.yaml`
- **WHEN** se carga la configuración
- **THEN** se obtiene sin error una configuración con `front = "jarvis"`, `worker = "viernes"`, `reply_mode = "auto"`, `models = {claude-haiku: claude-haiku-5-5, claude-sonnet: claude-sonnet-5-5}`, `voice = {stt: faster-whisper/small, tts: kokoro/ef_dora, vad: silero}`, `channels = [cli, web]`, `web = {port: 8787, host: 127.0.0.1}` y `limits = {tool_timeout_s: 20, task_timeout_s: 300, confirm_timeout_s: 60, mcp_connect_timeout_s: 10, token_alert: 50000, memory_max_lines: 200}`

#### Scenario: Fichero parcial
- **GIVEN** `config/tony.yaml` solo define `web: {port: 9000}`
- **WHEN** se carga la configuración
- **THEN** `web.port` es `9000`, `web.host` es `127.0.0.1` y el resto de campos conservan sus valores por defecto

#### Scenario: Alias de modelo adicional
- **GIVEN** `config/tony.yaml` define `models: {claude-opus: claude-opus-5}`
- **WHEN** se carga la configuración
- **THEN** `models` contiene `claude-opus`, y los alias por defecto `claude-haiku` y `claude-sonnet` siguen disponibles salvo que el fichero los sobrescriba

### Requirement: Validación con ruta de campo
Si `config/tony.yaml` contiene un valor inválido, el sistema SHALL rechazar la carga con un error que nombre la ruta del campo afectado (por ejemplo `limits.tool_timeout_s`) y el motivo, sin trazas de pila para el usuario.

#### Scenario: Tipo inválido en un límite
- **GIVEN** `config/tony.yaml` define `limits: {tool_timeout_s: "veinte"}`
- **WHEN** se carga la configuración
- **THEN** la carga falla con un error que incluye `limits.tool_timeout_s`

#### Scenario: Valor fuera del conjunto permitido
- **GIVEN** `config/tony.yaml` define `reply_mode: loud`
- **WHEN** se carga la configuración
- **THEN** la carga falla con un error que incluye `reply_mode` y los valores permitidos `auto`, `voice`, `text`, `both`

### Requirement: Front y worker distintos
El sistema SHALL rechazar la configuración cuando `front` y `worker` nombran al mismo agente.

#### Scenario: Mismo agente en ambos roles
- **GIVEN** `config/tony.yaml` define `front: viernes` y `worker: viernes`
- **WHEN** se carga la configuración
- **THEN** la carga falla con un error que indica que `front` y `worker` deben ser distintos

### Requirement: Variables de entorno desde `.env`
El sistema SHALL leer `config/.env` (si existe) y SHALL dejar sus pares clave/valor disponibles para la sustitución `${VAR}` en la configuración de tools de los agentes, sin exponerlos en la configuración serializada ni en logs.

#### Scenario: Variable definida solo en `.env`
- **GIVEN** `config/.env` contiene `NOTION_TOKEN=abc123` y la variable no existe en el entorno del proceso
- **WHEN** se carga la configuración
- **THEN** `NOTION_TOKEN` está disponible para sustituir `${NOTION_TOKEN}`

#### Scenario: Entorno del proceso tiene prioridad
- **GIVEN** `config/.env` contiene `HOME_NOTES=/a` y el entorno del proceso contiene `HOME_NOTES=/b`
- **WHEN** se resuelve `${HOME_NOTES}`
- **THEN** el valor resuelto es `/b`
