## MODIFIED Requirements

### Requirement: Disponibilidad de voz en la salud del servidor
`GET /api/health` SHALL incluir `voice: {available: bool, reason: str | null, stt: str, tts: str}` donde `available` es `true` solo si el extra `tony[voice]` está instalado y los alias `voice.stt`/`voice.tts` son válidos; `reason` SHALL explicar en español por qué no está disponible. Comprobar la disponibilidad SHALL NOT cargar ningún modelo.

#### Scenario: Voz disponible
- **GIVEN** el extra instalado, la configuración de voz por defecto y `voice.tts: kokoro/ef_dora`
- **WHEN** llega `GET /api/health`
- **THEN** la respuesta incluye `voice: {available: true, reason: null, stt: "faster-whisper/base", tts: "kokoro/ef_dora"}` y ningún modelo se ha cargado

#### Scenario: Extra ausente
- **GIVEN** el extra no instalado
- **WHEN** llega `GET /api/health`
- **THEN** `voice.available` es `false` y `voice.reason` contiene `uv sync --extra voice`
