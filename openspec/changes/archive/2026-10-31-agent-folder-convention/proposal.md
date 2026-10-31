# Proposal

## Why

Tony ya tiene dos agentes (`jarvis`, `viernes`) y una jerarquía de subagentes
(`archivista`, `calendario`) más skills bajo demanda, y la lista va a crecer. Hasta
ahora el formato de `agents/<nombre>/` (qué archivo va dónde, cómo se llama, qué
pertenece a cada agente) solo existe implícito en el código del loader
(`tony/core/loader/loader.py`, `tony/core/skills/loader.py`) y en el ejemplo que ya
hay en disco. No hay una convención escrita que guíe dónde debe vivir cada tipo
de archivo cuando se añada el próximo agente, subagente o skill, ni que distinga
qué patrones de otros proyectos (en particular DunDun, tomado como referencia)
aplican aquí y cuáles no soporta el loader actual de Tony.

Se revisó la arquitectura de DunDun (`dundun-config-<instancia>/{agents,
orchestrator, skills, prompts}/...`) como referencia externa. El layout actual de
Tony bajo `agents/<nombre>/` ya sigue, de hecho, el mismo principio de fondo
(una carpeta por agente con `agent.md`, `tool/tool.json`, `skills/<skill>/SKILL.md`
y, para el orquestador, `subagents/<nombre>/`). Lo que falta es declararlo como
convención exigible y señalar explícitamente los tres mecanismos de DunDun que
el loader de Tony no soporta hoy (`dundun.json`/`skill_modules` con distinción
skill-siempre-compuesta vs bajo-demanda, carpeta `prompts/` con copias de
`prompt_id`, y subagentes como archivos de enlace bajo `orchestrator/agents/`)
para no proponer por error un patrón que el código no puede cargar.

## What Changes

- Documentar, como especificación, la convención de carpetas y nombres de
  archivo que todo agente o subagente de Tony bajo `agents/` SHALL seguir,
  alineada con lo que `tony/core/loader` y `tony/core/skills` ya cargan hoy.
- Formalizar las reglas de nombres (kebab-case, singular, sin sufijos) para
  carpetas de agente, subagente y skill, y el árbol de archivos fijo esperado
  dentro de cada una (`agent.md`, `tool/tool.json` opcional, `skills/<skill>/SKILL.md`
  opcional, `subagents/<nombre>/` opcional y solo en agentes de profundidad 0).
- Revisar `agents/viernes/` y `agents/jarvis/` (incluidas las carpetas no
  trackeadas `agents/viernes/skills/{calendario,notas}/` y
  `agents/viernes/subagents/{archivista,calendario}/`) contra esa convención y
  dejar constancia explícita de qué ya cumple y qué, si algo, se mueve o se
  crea.
- Documentar como decisión explícita (no como trabajo pendiente) los tres
  mecanismos de DunDun que NO se adoptan por ahora porque el loader actual no
  los soporta: `dundun.json`/distinción skill siempre-compuesta vs bajo-demanda,
  carpeta `prompts/` con copias de `prompt_id`, y subagentes-como-enlace bajo un
  `orchestrator/agents/<handle>`. Ninguno de los tres se implementa en este
  cambio.
- **BREAKING**: ninguno. Este cambio no modifica el comportamiento de
  `tony/core/loader` ni `tony/core/skills`; es documentación de convención más,
  si hiciera falta, un reordenamiento de archivos que el loader ya sabe leer
  igual antes y después.

## Capabilities

### New Capabilities
- `agent-folder-convention`: convención de nombres y estructura de carpetas para
  `agents/<nombre>/`, sus `subagents/<nombre>/` y sus `skills/<nombre>/`, y la
  lista explícita de patrones de DunDun no adoptados por incompatibilidad con
  el loader actual.

### Modified Capabilities
(ninguna — `agent-loader`, `agent-skills` y `subagents` ya describen el
comportamiento de carga; este cambio no les modifica ningún requisito, solo
añade una convención de uso por encima.)

## Impact

- Código: ninguno (no se toca `tony/core/loader/*`, `tony/core/skills/*`).
- Archivos: posible reordenamiento dentro de `agents/viernes/` y
  `agents/jarvis/` (ver `design.md` y `tasks.md` para el detalle exacto; el
  layout actual ya cumple en gran parte, por lo que el movimiento esperado es
  mínimo).
- Tests: `tests/agents/test_bundled_agents.py` y cualquier otro test que
  referencie rutas literales bajo `agents/` (p. ej. nombres de carpeta de
  agente) si algún nombre cambiara; se revisan en `tasks.md`.
- Documentación: nueva spec `openspec/specs/agent-folder-convention/spec.md`
  como referencia para agentes futuros.
