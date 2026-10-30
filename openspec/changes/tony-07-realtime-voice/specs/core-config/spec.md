## MODIFIED Requirements

### Requirement: Configuración con valores por defecto
El sistema SHALL cargar `config/tony.yaml` en una estructura de configuración tipada con los campos `front`, `worker`, `reply_mode`, `models`, `voice`, `channels`, `web` y `limits`, y SHALL aplicar un valor por defecto a todo campo ausente.

#### Scenario: Fichero de configuración ausente
- **GIVEN** no existe `config/tony.yaml`
- **WHEN** se carga la configuración
- **THEN** se obtiene sin error una configuración con `front = "jarvis"`, `worker = "viernes"`, `reply_mode = "auto"`, `models = {claude-haiku: claude-haiku-5-5, claude-sonnet: claude-sonnet-5-5}`, `voice = {stt: faster-whisper/base, tts: "piper/es_MX-ald-medium?speed=0.95", vad: silero, end_silence_ms: 500, barge_in: true, barge_in_threshold: 0.8, barge_in_min_speech_ms: 280, cpu_threads: null, acknowledgements: ["Un momento, señor.", "Enseguida, señor.", "Ahora mismo lo reviso, señor."]}`, `channels = [cli, web]`, `web = {port: 8787, host: 127.0.0.1}` y `limits = {tool_timeout_s: 20, task_timeout_s: 300, confirm_timeout_s: 60, mcp_connect_timeout_s: 10, token_alert: 50000, memory_max_lines: 200}`

#### Scenario: Fichero parcial
- **GIVEN** `config/tony.yaml` solo define `web: {port: 9000}`
- **WHEN** se carga la configuración
- **THEN** `web.port` es `9000`, `web.host` es `127.0.0.1` y el resto de campos conservan sus valores por defecto

#### Scenario: Alias de modelo adicional
- **GIVEN** `config/tony.yaml` define `models: {claude-opus: claude-opus-5}`
- **WHEN** se carga la configuración
- **THEN** `models` contiene `claude-opus`, y los alias por defecto `claude-haiku` y `claude-sonnet` siguen disponibles salvo que el fichero los sobrescriba

## ADDED Requirements

### Requirement: Rangos de la configuración de voz
La sección `voice` SHALL validar `end_silence_ms` entre 300 y 1500, `barge_in_threshold` entre 0,5 y 0,99, `barge_in_min_speech_ms` entre 150 y 1000, `cpu_threads` nulo o entre 1 y 64, y `acknowledgements` con 1 a 10 frases no vacías de ≤ 60 caracteres; un valor fuera de rango SHALL fallar con la ruta del campo.

#### Scenario: Silencio fuera de rango
- **GIVEN** `voice: {end_silence_ms: 100}`
- **WHEN** se carga la configuración
- **THEN** falla con un mensaje que nombra `voice.end_silence_ms` y el rango 300–1500
