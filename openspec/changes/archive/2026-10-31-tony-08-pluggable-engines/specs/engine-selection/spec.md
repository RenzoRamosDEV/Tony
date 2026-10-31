# Spec Delta

## Purpose

Define cómo Tony declara, resuelve y cambia el motor de lenguaje (`claude_sdk`, `codex_cli` o un perfil `litellm`) que usa cada agente, sin afectar a los agentes que no declaran uno.

## ADDED Requirements

### Requirement: Mapa de perfiles de motor en la configuración global

`config/tony.yaml` SHALL aceptar un campo `engines: dict[str, EngineProfile]` donde cada perfil tiene `type` (`claude_sdk` | `codex_cli` | `litellm`) y, para `litellm`, un `model` (cadena de modelo de LiteLLM, por ejemplo `gpt-4o` o `gemini/gemini-2.0-flash`). El sistema SHALL incluir siempre el perfil implícito `claude_sdk` de `type: claude_sdk` aunque no se declare.

#### Scenario: Perfil por defecto siempre disponible
- **WHEN** `tony.yaml` no declara `engines`
- **THEN** el perfil `claude_sdk` existe y es el motor efectivo de cualquier agente sin `engine` en su frontmatter

#### Scenario: Perfil `litellm` sin modelo
- **WHEN** `tony.yaml` declara un perfil de `type: litellm` sin `model`
- **THEN** la carga de la configuración SHALL fallar nombrando el perfil y el campo `model` ausente

### Requirement: Campo `engine` en el frontmatter del agente

`agent.md` SHALL aceptar un campo opcional `engine` (str) que nombra un perfil de `engines`. Si está ausente, el motor efectivo del agente SHALL ser `claude_sdk`. Si nombra un perfil inexistente, la carga del agente SHALL fallar nombrando el perfil desconocido y los perfiles disponibles.

#### Scenario: Agente sin `engine` declarado
- **WHEN** `agent.md` no tiene el campo `engine`
- **THEN** el agente usa el motor `claude_sdk` y su comportamiento es idéntico al de antes de esta capacidad

#### Scenario: Agente con perfil desconocido
- **WHEN** `agent.md` declara `engine: inexistente` y `tony.yaml` no tiene ese perfil en `engines`
- **THEN** la carga del agente SHALL fallar nombrando `inexistente` y la lista de perfiles declarados

### Requirement: Resolución de alias de modelo por motor

El alias `model` del agente SHALL seguir resolviéndose contra la tabla `models` de la configuración global igual que hoy. Cada motor SHALL interpretar la cadena resuelta a su manera: un identificador de modelo de Claude para `claude_sdk`, un nombre de modelo para `-m` de Codex para `codex_cli`, o SHALL NOT usarla para `litellm` (ese motor usa el `model` del propio perfil `engines`, no el alias del agente).

#### Scenario: Alias reutilizado por un agente en `codex_cli`
- **WHEN** un agente con `engine: codex_cli` declara `model: claude-sonnet` y `models.claude-sonnet` resuelve a un identificador de modelo
- **THEN** ese identificador SHALL pasarse como `-m` a `codex exec`

### Requirement: Comando `tony engine set`

`tony engine set <agente> <perfil>` SHALL editar atómicamente el campo `engine` del `agent.md` del agente indicado, igual que la edición atómica de `tool.json` de `tony mcp add`, y SHALL fallar sin modificar el fichero si `<perfil>` no existe en `engines` o `<agente>` no existe.

#### Scenario: Cambio de motor válido
- **WHEN** se ejecuta `tony engine set viernes codex_cli` y `codex_cli` está declarado en `engines`
- **THEN** el frontmatter de `agents/viernes/agent.md` queda con `engine: codex_cli` y el resto del fichero no cambia

#### Scenario: Perfil inexistente
- **WHEN** se ejecuta `tony engine set viernes no_existe`
- **THEN** el comando SHALL fallar con un error que nombra `no_existe` y los perfiles disponibles, sin escribir el fichero

### Requirement: Comando `tony engine list`

`tony engine list [--agents-dir PATH]` SHALL listar cada agente y subagente cargado junto con su motor efectivo (declarado o `claude_sdk` por defecto) y el perfil `engines` resuelto.

#### Scenario: Listado con motores mixtos
- **WHEN** `jarvis` no declara `engine` y `viernes` declara `engine: codex_cli`
- **THEN** `tony engine list` SHALL mostrar `jarvis: claude_sdk` y `viernes: codex_cli`
