# Spec Delta

## Purpose

Define cómo un agente adquiere conocimiento bajo demanda mediante skills: el formato de `SKILL.md`, su validación, el índice que ve el modelo, la tool nativa `read_skill` y la activación automática por frases de `trigger`.

## ADDED Requirements

### Requirement: Formato de `SKILL.md`
Una skill SHALL vivir en `agents/<agente>/skills/<nombre>/SKILL.md` con un frontmatter YAML delimitado por `---` que acepta `name` (str, obligatorio, igual al nombre de la carpeta), `description` (str, obligatoria, ≤ 200 caracteres) y `trigger` (lista de str, por defecto vacía), seguido de un cuerpo markdown. La skill cargada SHALL exponer `name`, `description`, `triggers`, `body` y `path`.

#### Scenario: Skill completa
- **GIVEN** `agents/viernes/skills/resumen-web/SKILL.md` con frontmatter `name: resumen-web`, `description: Resume una página web en 5 viñetas con fuente y fecha.`, `trigger: ["resume esta web", "resúmeme la página"]` y cuerpo `1. Descarga la página con \`fetch.fetch\`.\n2. Extrae el contenido principal…`
- **WHEN** se carga la skill
- **THEN** `name` es `resumen-web`, `description` es la indicada, `triggers` son las dos frases, `body` empieza por `1. Descarga la página` y `path` apunta a la carpeta `resumen-web`

#### Scenario: Trigger ausente
- **GIVEN** un `SKILL.md` cuyo frontmatter solo define `name` y `description`
- **WHEN** se carga la skill
- **THEN** `triggers` es una lista vacía y la carga no falla

#### Scenario: Nombre distinto de la carpeta
- **GIVEN** `skills/resumen-web/SKILL.md` con `name: resumen`
- **WHEN** se carga la skill
- **THEN** la carga falla con un error que nombra `resumen-web`, `resumen` y el campo `name`

#### Scenario: Descripción demasiado larga
- **GIVEN** un `SKILL.md` con `description` de 201 caracteres
- **WHEN** se carga la skill
- **THEN** la carga falla con un error que nombra `description` y el límite `200`

#### Scenario: Descripción ausente
- **GIVEN** un `SKILL.md` sin `description`
- **WHEN** se carga la skill
- **THEN** la carga falla con un error que nombra `description`

#### Scenario: Frontmatter ausente
- **GIVEN** un `SKILL.md` sin delimitadores `---`
- **WHEN** se carga la skill
- **THEN** la carga falla con un error que indica que falta el frontmatter

### Requirement: Skill inválida no bloquea al agente
Al cargar la carpeta `skills/` de un agente, cada skill inválida SHALL registrarse como error (con el nombre de la carpeta y el motivo) y las demás skills SHALL cargarse; una carpeta `skills/` ausente SHALL equivaler a una lista vacía.

#### Scenario: Una skill rota entre varias
- **GIVEN** `skills/a/SKILL.md` válida y `skills/b/SKILL.md` sin `description`
- **WHEN** se cargan las skills del agente
- **THEN** el agente tiene la skill `a`, su lista de errores de skills contiene una entrada que nombra `b` y `description`, y la carga del agente no falla

#### Scenario: Sin carpeta de skills
- **GIVEN** un agente sin carpeta `skills/`
- **WHEN** se carga el agente
- **THEN** la lista de skills está vacía y no hay errores

### Requirement: Índice de skills en el system prompt
El system prompt del agente SHALL incluir únicamente un índice `Skills disponibles:` con una línea `- <name>: <description>` por skill, sin el cuerpo de ninguna; sin skills SHALL NOT incluirse el índice. SHALL aplicarse tanto al `front` como al `worker`.

#### Scenario: Índice sin cuerpos
- **GIVEN** un `worker` con las skills `resumen-web` (descripción `Resume una página web`) y `informe` (descripción `Redacta un informe`)
- **WHEN** se construye su system prompt
- **THEN** contiene `Skills disponibles:`, `- resumen-web: Resume una página web` y `- informe: Redacta un informe`, y no contiene ninguna línea del cuerpo de las skills

#### Scenario: Agente sin skills
- **GIVEN** un agente sin skills
- **WHEN** se construye su system prompt
- **THEN** no contiene `Skills disponibles`

### Requirement: Tool nativa `read_skill`
Cuando `tool.json.native` incluye `read_skill`, el servidor nativo `tony` del agente SHALL exponer `read_skill(nombre: str) -> str` que devuelve el cuerpo completo de la skill. Un nombre desconocido SHALL devolver un error que lista las skills disponibles.

#### Scenario: Cuerpo de una skill
- **GIVEN** un agente con la skill `resumen-web` y `native: ["read_skill"]`
- **WHEN** el modelo llama a `read_skill("resumen-web")`
- **THEN** recibe el cuerpo markdown completo de la skill

#### Scenario: Skill desconocida
- **GIVEN** un agente con las skills `resumen-web` e `informe`
- **WHEN** el modelo llama a `read_skill("traducir")`
- **THEN** recibe un error que incluye `traducir`, `resumen-web` e `informe`

#### Scenario: Agente sin skills
- **GIVEN** un agente sin skills y `native: ["read_skill"]`
- **WHEN** el modelo llama a `read_skill("x")`
- **THEN** recibe un error que indica que no hay skills disponibles

### Requirement: Activación automática por trigger
Si el texto del usuario contiene alguna frase de `trigger` de una skill, comparando sin distinguir mayúsculas ni acentos, el sistema SHALL inyectar en el turno el cuerpo de esa skill como bloque `<skill name="<name>">…</skill>` antes del texto del usuario, sin esperar a que el modelo llame a `read_skill`. Cada skill activada SHALL inyectarse una sola vez por turno.

#### Scenario: Trigger de skill por frase
- **GIVEN** la skill `resumen-web` con trigger `resume esta web`
- **WHEN** el usuario escribe `Resume esta web: https://x.y`
- **THEN** el turno del agente incluye el bloque `<skill name="resumen-web">` con el cuerpo de la skill sin llamada previa a `read_skill`

#### Scenario: Acentos y mayúsculas
- **GIVEN** la skill `resumen-web` con trigger `resúmeme la página`
- **WHEN** el usuario escribe `RESUMEME LA PAGINA de hoy`
- **THEN** el turno incluye el bloque `<skill name="resumen-web">`

#### Scenario: Sin coincidencia
- **GIVEN** la skill `resumen-web` con trigger `resume esta web`
- **WHEN** el usuario escribe `¿qué hora es?`
- **THEN** el turno no contiene ningún bloque `<skill`

#### Scenario: Varias skills activadas
- **GIVEN** las skills `a` (trigger `informe`) y `b` (trigger `semanal`)
- **WHEN** el usuario escribe `prepara el informe semanal`
- **THEN** el turno incluye los bloques `<skill name="a">` y `<skill name="b">`, cada uno una sola vez

#### Scenario: Activación en el worker
- **GIVEN** un `worker` con la skill `resumen-web` (trigger `resume esta web`)
- **WHEN** recibe una tarea con `objetivo` `resume esta web: https://x.y`
- **THEN** la petición enviada al modelo incluye el bloque `<skill name="resumen-web">`
