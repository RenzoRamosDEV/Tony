# Design

## Context

Ver `proposal.md` (Why) para la motivación. Resumen técnico necesario para
entender el resto de este documento:

- `tony/core/loader/loader.py:load_agent` carga `agents/<handle>/agent.md`
  (frontmatter + cuerpo), `agents/<handle>/tool/tool.json` (opcional),
  `agents/<handle>/skills/` (vía `tony/core/skills/loader.py:load_skills`) y,
  solo a profundidad 0, `agents/<handle>/subagents/<handle>/` (un nivel, cada
  subagente SHALL NOT tener su propia carpeta `subagents/`; si declara
  `run_subagent` en `native` se elimina con un warning).
- `tony/core/skills/loader.py:parse_skill` exige `skills/<skill>/SKILL.md` con
  `name` en el frontmatter igual al nombre de la carpeta `<skill>`.
- El inventario actual en disco:
  ```
  agents/jarvis/{agent.md, tool/tool.json}
  agents/viernes/{agent.md, tool/tool.json,
    skills/{resumen-web, calendario, notas}/SKILL.md,
    subagents/{archivista, calendario}/{agent.md, tool/tool.json},
    subagents/investigador/agent.md}
  ```
- DunDun usa `dundun-config-<instancia>/{agents/<handle>/{AGENTS.md,
  dundun.json, tools.json, skills/<handle>}, orchestrator/{..., agents/<handle>
  (enlaces)}, skills/<handle>.md, prompts/}`. Tres piezas de ese patrón no
  tienen equivalente en el loader de Tony hoy: `dundun.json` (con
  `skill_modules` vs skill bajo-demanda), `prompts/`, y subagentes como
  archivo de enlace bajo `orchestrator/agents/`.

## Goals / Non-Goals

**Goals:**
- Declarar la convención de carpetas/nombres ya implícita en el loader como
  spec exigible (`agent-folder-convention`), de modo que agregar el próximo
  agente, subagente o skill no requiera leer el código fuente del loader.
- Verificar el inventario actual (`agents/viernes/`, `agents/jarvis/`,
  incluidas las carpetas no trackeadas `skills/{calendario,notas}` y
  `subagents/{archivista,calendario}`) contra esa convención y dejar
  constancia de qué cumple y qué no.
- Dejar escrito, como decisión y no como pendiente, qué tres patrones de
  DunDun no se adoptan por incompatibilidad con el loader actual.

**Non-Goals:**
- No se modifica `tony/core/loader` ni `tony/core/skills` en este cambio.
- No se introduce `dundun.json`, `prompts/`, ni enlaces de subagente al estilo
  `orchestrator/agents/<handle>`; adoptar cualquiera de los tres requeriría un
  cambio de código propio, fuera de este alcance.
- No se decide todavía si Tony necesitará alguna vez distinguir skill
  "siempre compuesta" de "bajo demanda" a nivel de runtime (hoy todas las
  skills de Tony son bajo demanda, cargadas vía `read_skill`); esa es una
  decisión de producto para una propuesta futura, no de esta.

## Decisions

**D1. Mantener `agents/<handle>/` plano, sin una carpeta raíz por instancia
al estilo `dundun-config-<instancia>/`.**
Tony hoy corre una sola instancia por despliegue (un `agents/` por checkout,
seleccionado por `config/tony.yaml`), así que la capa "instancia" de DunDun no
tiene contraparte que resolver. Si en el futuro Tony soporta múltiples
instancias con catálogos de agentes distintos en el mismo repo, esa
necesidad se evalúa en una propuesta propia; hoy introducir ese nivel sería
especular sin un caso de uso real (ver Hard Rule de "no expandir el alcance
más allá de la especificación aprobada").

**D2. No crear `prompts/` ni separar el system prompt de `agent.md`.**
El loader lee el cuerpo markdown de `agent.md` directamente como
`system_prompt`; no hay concepto de `prompt_id` ni de prompt compartido entre
agentes. Crear una carpeta `prompts/` vacía o con copias manuales no
cambiaría qué lee el loader y generaría una fuente de verdad duplicada.
Alternativa descartada: copiar el patrón igual, manteniendo `prompts/` como
documentación adicional sin que el loader la lea — descartada porque
introduce un artefacto que puede quedar desincronizado con `agent.md` sin que
nada lo detecte.

**D3. No introducir `dundun.json` ni la distinción skill
siempre-compuesta/bajo-demanda.**
Hoy toda skill de Tony es "bajo demanda": se lista en el índice y se carga
completa con `read_skill` cuando el agente decide usarla; no existe
inyección automática de una skill en cada turno. Añadir un campo
`skill_modules` sin que el loader lo lea sería un campo muerto en
`agent.md`; el frontmatter de `agent.md` además rechaza explícitamente claves
reservadas no soportadas (`RESERVED_HEADER_KEYS` en
`tony/core/loader/loader.py`), así que un campo inventado o se ignora
silenciosamente o rompe la carga. Alternativa descartada: simular la
distinción solo con una convención de nombres (p. ej. prefijo `always-` en la
carpeta de skill) sin cambio de loader — descartada porque no tendría efecto
en runtime y confundiría a quien lea la carpeta esperando que signifique algo.

**D4. Mantener `jarvis` y `viernes` como agentes de nivel superior hermanos,
no como orquestador con subagente enlazado.**
En DunDun, el orquestador delega en agentes reales vía un archivo de enlace en
`orchestrator/agents/<handle>` (el contenido del enlace se ignora; solo
importa el nombre). El loader de Tony no tiene ese mecanismo: `_load_subagents`
carga cada carpeta bajo `subagents/` como una definición de agente completa e
independiente, no como una referencia a otra carpeta. Si `jarvis` tuviera una
carpeta `subagents/viernes/`, el loader cargaría una copia separada y
desincronizada de `viernes`, no el agente real. La delegación de `jarvis` a
`viernes` ya existe, pero a nivel de tool (`delegate`, ver
`agents/jarvis/tool/tool.json` y `agents/jarvis/agent.md`), no de carpeta.
Alternativa descartada: añadir soporte de "enlace" en el loader para igualar
el patrón de DunDun — descartada para este cambio porque es un cambio de
código, no de convención, y no fue pedido; queda anotada como posible
propuesta futura independiente si se necesitara.

**D5. El inventario actual de `agents/viernes/` y `agents/jarvis/` no
requiere mover archivos.**
Verificado contra los requisitos de la spec: `jarvis/{agent.md,
tool/tool.json}` y `viernes/{agent.md, tool/tool.json, skills/<skill>/SKILL.md,
subagents/<handle>/{agent.md, tool/tool.json}}` ya cumplen el árbol fijo, los
nombres de carpeta ya están en kebab-case, y cada `SKILL.md` ya tiene `name`
igual a su carpeta (`resumen-web`, `calendario`, `notas`). No hay archivo fuera
de lugar ni carpeta con sufijo de rol o versión. La "reorganización" que pedía
la tarea original se resuelve, por tanto, formalizando la convención por
escrito (lo que hace este cambio) en vez de moviendo archivos que ya están en
el sitio correcto; `tasks.md` deja el chequeo como paso verificable en vez de
asumirlo.

## Risks / Trade-offs

- [Riesgo] Declarar la convención sin automatizarla (sin un linter/test que la
  haga cumplir) permite que un futuro agente se añada sin seguirla. →
  Mitigación: `tasks.md` incluye extender
  `tests/agents/test_bundled_agents.py` con una comprobación de estructura
  genérica (toda carpeta bajo `agents/` y `subagents/` tiene como máximo
  `agent.md`, `tool/`, `skills/`, `subagents/`) para que la convención falle
  en CI, no solo en revisión humana.
- [Riesgo] Documentar los tres patrones de DunDun como "no adoptados" podría
  leerse como un rechazo permanente en vez de una decisión revisable. →
  Mitigación: la spec los enmarca como bloqueados por falta de soporte del
  loader, no por desacuerdo de diseño, y exige que cualquier propuesta futura
  que los quiera adoptar proponga primero el cambio de loader correspondiente.

## Migration Plan

No aplica despliegue ni rollback: no hay cambio de código ni de datos en
runtime. Los únicos "pasos" son documentar la spec (este cambio) y, si
`tasks.md` encuentra alguna desviación real al verificar el inventario actual,
corregirla con un commit de solo movimiento de archivos (sin cambios de
contenido) antes de archivar el cambio.
