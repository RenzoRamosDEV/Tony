# cli-doctor Specification

## Purpose
Define el diagnóstico de una instalación de Tony desde la línea de comandos: las comprobaciones de `tony doctor`, su variante sin red ni procesos `tony config validate`, el formato `✓/✗` con sugerencia accionable y los códigos de salida.

## Requirements

### Requirement: Comando `tony doctor`
`tony doctor [--offline] [--agents-dir PATH] [--config PATH]` SHALL ejecutar todas las comprobaciones de instalación y reportar cada una en una línea que empieza por `✓`, `✗` o un marcador informativo, seguida del nombre de la comprobación, el detalle y, en caso de `✗`, una sugerencia accionable en español. Con `--offline` SHALL omitirse la petición al modelo.

#### Scenario: Instalación sana sin modelo
- **GIVEN** un repositorio temporal con `tony.yaml` válido, `.env` con permisos `600`, `viernes` con el servidor stdio falso `fake` y `confirm: ["fake.destroy"]`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** cada línea de comprobación empieza por `✓` salvo la del modelo, que indica que se omitió por `--offline`, y el código de salida es `0`

#### Scenario: Fallos inducidos
- **GIVEN** un repositorio temporal con `.env` con permisos `644`, `agents/roto/agent.md` con `role: helper`, `viernes` con el servidor `broken` (`command: "/no/existe"`) y `allow: ["fake.nada"]`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗` para los permisos de `.env` con la sugerencia `chmod 600 config/.env`, `✗` para `roto` con el error de carga, `✗` para `broken` con su error y `✗` para el patrón `fake.nada` indicando que no coincide con ninguna tool; el código de salida es `1`

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

### Requirement: Comprobaciones de configuración y agentes
`tony doctor` SHALL comprobar que `config/tony.yaml` es válido, que `config/.env` existe con permisos `600`, que cada agente, subagente y skill cargan, y que toda variable `${VAR}` de los `tool.json` está definida; cada fallo SHALL nombrar el fichero o el agente afectado.

#### Scenario: Variable sin resolver
- **GIVEN** `viernes` con `url: "${NOTION_URL}"` y `NOTION_URL` sin definir
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗` que nombra `NOTION_URL` y `viernes` y sugiere definirla en `config/.env`

#### Scenario: .env ausente
- **GIVEN** no existe `config/.env`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗` que nombra `config/.env` y sugiere crearlo con permisos `600`

#### Scenario: Skill inválida
- **GIVEN** `viernes` con una skill sin `description`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗` que nombra la skill y `description`

### Requirement: Comprobaciones de servidores MCP
`tony doctor` SHALL conectar a cada servidor MCP declarado por cada agente y subagente con el timeout de conexión configurado, reportar `✓ <agente>/<servidor>: N tools` o `✗` con el error, y comprobar que cada patrón de `allow` y de `confirm` coincide con al menos una tool listada.

#### Scenario: Servidor correcto
- **GIVEN** `viernes` con el servidor stdio falso `fake` (4 tools)
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✓` con `viernes`, `fake` y `4 tools`

#### Scenario: Patrón sin tool
- **GIVEN** `viernes` con `confirm: ["fake.nada"]`
- **WHEN** se ejecuta `tony doctor --offline`
- **THEN** la salida contiene `✗` que nombra `fake.nada` y sugiere revisar `allow`/`confirm`

### Requirement: Código de salida de `tony doctor`
El código de salida SHALL ser `1` si alguna comprobación resulta `✗` y `0` en caso contrario; las líneas informativas SHALL NOT afectar al código de salida.

#### Scenario: Un solo fallo
- **GIVEN** todas las comprobaciones correctas salvo los permisos de `.env`
- **WHEN** termina `tony doctor --offline`
- **THEN** el código de salida es `1`

### Requirement: Comando `tony config validate`
`tony config validate [--agents-dir PATH] [--config PATH]` SHALL ejecutar únicamente las comprobaciones que no requieren red ni procesos (`tony.yaml`, `.env`, carga de agentes, subagentes y skills, variables `${VAR}`, presencia de `node`/`npx`), con el mismo formato y los mismos códigos de salida que `tony doctor`, sin conectar a ningún MCP ni al modelo.

#### Scenario: Validación sin procesos
- **GIVEN** `viernes` con un servidor `command: "/no/existe"`
- **WHEN** se ejecuta `tony config validate`
- **THEN** no se intenta arrancar el servidor, la salida no contiene ninguna línea de conexión MCP, y el código de salida es `0` si el resto de comprobaciones pasan

#### Scenario: Configuración inválida
- **GIVEN** `tony.yaml` con `reply_mode: loud`
- **WHEN** se ejecuta `tony config validate`
- **THEN** la salida contiene `✗` con `reply_mode` y los valores permitidos, y el código de salida es `1`

### Requirement: Ayuda en español
`tony doctor --help` y `tony config validate --help` SHALL describir el comando y sus opciones en español, y `tony --help` SHALL listar `doctor` y `config`.

#### Scenario: Ayuda de doctor
- **WHEN** se ejecuta `tony doctor --help`
- **THEN** la salida describe `--offline`, `--agents-dir` y `--config` en español

### Requirement: Comprobaciones de motores de agente

`tony doctor` SHALL comprobar, para cada perfil de `engines` en uso por algún agente o subagente cargado, lo que corresponda a su `type`, en el mismo formato `✓/✗` con sugerencia accionable que el resto de `tony doctor`.

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
- **THEN** la salida no contiene ninguna línea de comprobación de `litellm`
