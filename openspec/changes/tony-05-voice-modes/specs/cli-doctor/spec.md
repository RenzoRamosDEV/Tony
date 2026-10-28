# Spec Delta

## MODIFIED Requirements

### Requirement: Comprobaciones del entorno
`tony doctor` SHALL comprobar la versión de Python (3.12), la presencia del CLI `claude` en el `PATH` y su autenticación mediante una petición mínima de un solo turno al modelo `claude-haiku` (omitida con `--offline`), la presencia de `node` y `npx` cuando algún MCP los usa, y la instalación del extra de voz, `espeak-ng` y la caché de modelos de voz, que SHALL reportarse solo como información; los alias `voice.stt` y `voice.tts` SHALL comprobarse y un alias inválido SHALL reportarse como `✗` con los valores válidos.

#### Scenario: node y npx
- **GIVEN** un MCP con `command: npx` y `npx` ausente del `PATH`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗` que nombra `npx` y sugiere instalar Node.js

#### Scenario: claude ausente
- **GIVEN** `claude` ausente del `PATH`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗` que nombra `claude` y sugiere instalar y autenticar Claude Code CLI

#### Scenario: Extras de voz solo informan
- **GIVEN** los extras `tony[voice]` no instalados y `espeak-ng` presente
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene una línea informativa que indica que `voice` no está instalado con la sugerencia `uv sync --extra voice`, una línea `✓` para `espeak-ng`, y ninguna de las dos cuenta como `✗`

#### Scenario: espeak-ng ausente con el extra instalado
- **GIVEN** el extra instalado y `espeak-ng` ausente del `PATH`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene una línea informativa para `espeak-ng` que sugiere `rpm-ostree install espeak-ng` o `brew install espeak-ng` y no cuenta como `✗`

#### Scenario: Alias de voz inválido
- **GIVEN** `voice.tts: kokoro/no_existe`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗` que nombra `voice.tts`, `kokoro/no_existe` y las voces válidas (`ef_dora`, `em_alex`, `em_santa`), y el código de salida es `1`

#### Scenario: Modelos sin descargar
- **GIVEN** el extra instalado y la caché de modelos vacía
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene una línea informativa que indica que los modelos de voz no están en caché y sugiere `tony voice warmup`, sin contar como `✗`
