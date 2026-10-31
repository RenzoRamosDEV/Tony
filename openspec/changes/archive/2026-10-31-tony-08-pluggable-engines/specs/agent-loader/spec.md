# Spec Delta

## MODIFIED Requirements

### Requirement: Definición de agente en `agent.md`
El sistema SHALL cargar `agents/<nombre>/agent.md` como un frontmatter YAML delimitado por `---` seguido de un cuerpo markdown que es el system prompt. El frontmatter SHALL aceptar: `name` (str, obligatorio), `role` (`front` | `worker`, obligatorio), `model` (alias, obligatorio), `engine` (str, opcional, por defecto `claude_sdk`), `persona {address: "" , language: "es"}`, `style {voice: "", text: ""}`, `max_steps` (entero 1..200, por defecto 20) y `wait_phrase` (por defecto `"Dame un momento."`).

#### Scenario: Agente completo
- **GIVEN** `agents/jarvis/agent.md` con frontmatter `name: jarvis`, `role: front`, `model: claude-haiku`, `persona: {address: señor, language: es}`, `style: {voice: "Frases cortas, sin markdown, números redondeados.", text: "Markdown, detalle completo, tablas si ayudan."}`, `max_steps: 20` y cuerpo `Eres Jarvis, el asistente personal de Renzo...`
- **WHEN** se carga el agente
- **THEN** la definición resultante tiene esos valores, `system_prompt` igual al cuerpo sin el frontmatter y `path` apuntando a la carpeta del agente

#### Scenario: Campos opcionales ausentes
- **GIVEN** un `agent.md` cuyo frontmatter solo define `name`, `role` y `model`
- **WHEN** se carga el agente
- **THEN** `persona.language` es `es`, `persona.address` es vacío, `max_steps` es `20`, `wait_phrase` es `Dame un momento.` y `engine` es `claude_sdk`

#### Scenario: `max_steps` fuera de rango
- **GIVEN** un `agent.md` con `max_steps: 500`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que nombra `max_steps` y el rango permitido `1..200`

#### Scenario: Rol inválido
- **GIVEN** un `agent.md` con `role: helper`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que nombra `role` y los valores permitidos `front` y `worker`

#### Scenario: Frontmatter ausente
- **GIVEN** un `agent.md` sin delimitadores `---`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que indica que falta el frontmatter

#### Scenario: `engine` declarado y válido
- **GIVEN** un `agent.md` con `engine: codex_cli` y `tony.yaml` con ese perfil declarado en `engines`
- **WHEN** se carga el agente
- **THEN** la definición resultante tiene `engine: codex_cli`

#### Scenario: `engine` desconocido
- **GIVEN** un `agent.md` con `engine: no_declarado` y `tony.yaml` sin ese perfil en `engines`
- **WHEN** se carga el agente
- **THEN** la carga falla con un error que nombra `no_declarado` y los perfiles disponibles
