# agent-folder-convention Specification

## Purpose

Fija, como convención exigible, la estructura de carpetas y los nombres de
archivo que todo agente, subagente y skill de Tony SHALL seguir bajo
`agents/`, para que añadir el próximo agente no dependa de leer el código del
loader para inferir el patrón.

## Requirements

### Requirement: Carpeta de agente de nivel superior
Todo agente de nivel superior SHALL vivir en `agents/<handle>/`, con `<handle>`
en kebab-case, en minúsculas, sin sufijos de rol ni de versión (por ejemplo
`viernes`, no `viernes-agent` ni `viernes_v2`). El nombre de la carpeta SHALL
ser el identificador único del agente en todo el sistema (configuración,
tests, documentación).

#### Scenario: Nuevo agente de nivel superior
- **WHEN** se añade un agente nuevo al catálogo de Tony
- **THEN** su carpeta se crea como `agents/<handle>/` con `<handle>` en
  kebab-case y sin sufijos de rol o versión

### Requirement: Archivos fijos dentro de la carpeta de un agente
Dentro de `agents/<handle>/` (o `agents/<handle>/subagents/<handle>/`) SHALL
existir exactamente `agent.md` en la raíz de la carpeta del agente; SHALL
existir como máximo un `tool/tool.json`; SHALL existir como máximo una carpeta
`skills/`; y, solo si el agente es de nivel superior (profundidad 0), SHALL
existir como máximo una carpeta `subagents/`. Ningún otro archivo o carpeta de
configuración del agente SHALL vivir fuera de este árbol fijo.

#### Scenario: Agente worker sin subagentes
- **WHEN** un agente no delega en ningún subagente
- **THEN** su carpeta no incluye una carpeta `subagents/`

#### Scenario: Subagente con tools propias
- **WHEN** un subagente necesita tools que no hereda de su padre
- **THEN** declara `tool/tool.json` dentro de su propia carpeta
  `subagents/<handle>/`, nunca en otra ruta

### Requirement: Carpeta de subagente
Un subagente SHALL vivir en `agents/<handle-padre>/subagents/<handle>/`, con la
misma regla de nombre en kebab-case que un agente de nivel superior, y SHALL
seguir el mismo árbol de archivos fijo que un agente de nivel superior, salvo
que SHALL NOT contener su propia carpeta `subagents/` (el loader solo soporta
un nivel de profundidad).

#### Scenario: Subagente con subagente propio (rechazado por convención)
- **WHEN** alguien intenta crear `subagents/<a>/subagents/<b>/` dentro de un
  subagente existente
- **THEN** la convención lo marca como inválido antes de intentar cargarlo,
  porque el loader solo soporta un nivel de profundidad

### Requirement: Carpeta y archivo de skill
Una skill de agente SHALL vivir en `agents/<handle>/skills/<skill>/SKILL.md`
(o bajo la carpeta `skills/` de un subagente), con `<skill>` en kebab-case. El
campo `name` del frontmatter de `SKILL.md` SHALL ser idéntico al nombre de la
carpeta `<skill>` que lo contiene. Una skill SHALL NOT declararse en más de una
carpeta de agente; si varios agentes necesitan el mismo procedimiento, cada uno
SHALL tener su propia copia con su propio `SKILL.md`, no un enlace compartido.

#### Scenario: Nombre de skill no coincide con la carpeta
- **WHEN** el frontmatter de un `SKILL.md` declara un `name` distinto al de su
  carpeta contenedora
- **THEN** la convención lo marca como inválido, igual que lo rechaza hoy
  `tony/core/skills/loader.py`

### Requirement: Patrones de DunDun no adoptados
La convención SHALL documentar explícitamente, como decisión y no como
pendiente, los patrones de DunDun que NO se adoptan en Tony mientras el
loader no los soporte. Ninguna propuesta futura SHALL introducir alguno de
esos patrones sin antes proponer y aprobar el cambio de código
correspondiente en `tony/core/loader` o `tony/core/skills`.

#### Scenario: Propuesta futura intenta copiar `dundun.json` sin cambiar el loader
- **WHEN** una propuesta futura sugiere añadir un `dundun.json` por agente sin
  modificar `tony/core/loader`
- **THEN** la propuesta se considera incompleta por esta convención, porque
  introduce un archivo que el loader actual no lee ni valida

### Requirement: Lista cerrada de patrones no adoptados
Los patrones de DunDun no adoptados por esta convención SHALL ser exactamente:
(a) un archivo de metadatos por agente al estilo `dundun.json` con distinción
entre skill "siempre compuesta" y skill "bajo demanda"; (b) una carpeta
`prompts/` con copias locales de prompts referenciados por id; (c) subagentes
representados como archivos de enlace bajo una carpeta
`orchestrator/agents/<handle>` que apunten a la carpeta real del agente.

#### Scenario: Propuesta futura intenta enlazar un subagente en vez de declararlo completo
- **WHEN** una propuesta futura sugiere representar un subagente como un
  archivo de enlace bajo `orchestrator/agents/<handle>` en vez de una carpeta
  `subagents/<handle>/` completa
- **THEN** la propuesta se considera incompleta por esta convención, porque
  `tony/core/loader._load_subagents` carga cada carpeta como una definición
  de agente completa, no como una referencia a otra carpeta
