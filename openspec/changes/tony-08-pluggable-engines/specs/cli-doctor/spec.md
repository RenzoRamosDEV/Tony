# Spec Delta

## ADDED Requirements

### Requirement: Comprobaciones de motores de agente

`tony doctor` SHALL comprobar, para cada perfil de `engines` en uso por algún agente o subagente cargado, lo que corresponda a su `type`, en el mismo formato `✓/✗` con sugerencia accionable que el resto de `tony doctor`.

#### Scenario: `codex_cli` sano
- **GIVEN** `viernes` con `engine: codex_cli` y el binario `codex` presente y autenticado
- **WHEN** se ejecuta `tony doctor`
- **THEN** la salida contiene `✓ codex: autenticado`

#### Scenario: `codex_cli` omitido en modo offline
- **GIVEN** `viernes` con `engine: codex_cli`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la invocación de diagnóstico de `codex` se omite igual que la de `claude`, y la presencia del binario en `PATH` sigue comprobándose

#### Scenario: `codex_cli` sin binario
- **GIVEN** `viernes` con `engine: codex_cli` y `codex` ausente del `PATH`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗ codex: no encontrado en PATH` con una sugerencia de instalación, y el código de salida es `1`

#### Scenario: `litellm` con clave presente
- **GIVEN** `jarvis` con `engine: openai_gpt` de `type: litellm` y `model: gpt-4o`, y `OPENAI_API_KEY` definida en `config/.env`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✓ litellm/openai_gpt: clave presente`

#### Scenario: `litellm` sin clave
- **GIVEN** `jarvis` con `engine: openai_gpt` de `type: litellm` y `model: gpt-4o`, y `OPENAI_API_KEY` sin definir
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗ litellm/openai_gpt: falta OPENAI_API_KEY` con una sugerencia de definirla en `config/.env`, y el código de salida es `1`

#### Scenario: Sin agentes usando motores alternativos
- **GIVEN** ningún agente declara `engine` distinto de `claude_sdk`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida no contiene ninguna línea de comprobación de `codex` ni de `litellm`
