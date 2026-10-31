# Tasks

## 1. Inventario y verificación contra la convención

- [x] 1.1 Listar con `find agents -mindepth 1 -maxdepth 6` todas las carpetas
      y archivos reales bajo `agents/` (incluidas las no trackeadas
      `agents/viernes/skills/{calendario,notas}/` y
      `agents/viernes/subagents/{archivista,calendario}/`) y verificar que
      cada handle de agente/subagente/skill está en kebab-case y sin sufijos
      de rol o versión, según `specs/agent-folder-convention/spec.md`
      (Requirement "Carpeta de agente de nivel superior" / "Carpeta de
      subagente" / "Carpeta y archivo de skill").
- [x] 1.2 Para cada carpeta de agente y subagente, verificar que solo
      contiene `agent.md`, como máximo un `tool/tool.json`, como máximo una
      carpeta `skills/` y (solo en agentes de profundidad 0) como máximo una
      carpeta `subagents/`, sin archivos sueltos adicionales; verificación:
      ningún archivo fuera de ese árbol aparece en el listado de 1.1.
- [x] 1.3 Para cada `SKILL.md` bajo `agents/`, verificar que el `name` del
      frontmatter coincide con el nombre de su carpeta contenedora;
      verificación: `grep -n "^name:" agents/*/skills/*/SKILL.md
      agents/*/subagents/*/skills/*/SKILL.md 2>/dev/null` comparado a mano con
      cada ruta, o ejecutar `pytest tests/agents/test_bundled_agents.py -q`
      (ya ejercita `load_agent`/`load_skills`, que falla si algún `name` no
      coincide).
- [x] 1.4 Confirmar que ninguna carpeta bajo `agents/` introduce un
      `dundun.json`, una carpeta `prompts/` o un archivo de enlace de
      subagente (contenido ignorado, solo el nombre importa); verificación:
      `find agents -iname 'dundun.json' -o -iname 'prompts' -o -ipath
      '*orchestrator/agents*'` no devuelve resultados.
- [x] 1.5 Documentar en una nota breve (puede ir en la descripción del PR o
      commit de este cambio, no en código) el resultado de 1.1-1.4: si el
      inventario actual ya cumple la convención sin mover nada (resultado
      esperado según `design.md` Decisión D5), dejarlo constatado; si se
      encuentra una desviación real, corregirla con un commit de solo
      movimiento de archivos (`git mv`) antes de continuar, y registrar aquí
      qué se movió.

      **Resultado (constatado, sin movimientos):** `find agents -mindepth 1
      -maxdepth 6` muestra que `agents/jarvis/` y `agents/viernes/` (con sus
      `skills/{resumen-web,calendario,notas}/` y
      `subagents/{archivista,calendario,investigador}/`) ya siguen el árbol
      fijo exacto: `agent.md` obligatorio, `tool/tool.json` opcional (ausente
      en `investigador`), `skills/` opcional (ausente en `jarvis` y en los
      subagentes), `subagents/` solo en `viernes` (profundidad 0), y ningún
      subagente anida su propio `subagents/`. Todos los handles están en
      kebab-case sin sufijos de rol/versión. `find agents -iname
      'dundun.json' -o -iname 'prompts' -o -ipath '*orchestrator/agents*'` no
      devuelve resultados. Los tres `name:` de frontmatter en
      `agents/viernes/skills/*/SKILL.md` coinciden con su carpeta
      (`resumen-web`, `notas`, `calendario`). No se movió ningún archivo.

## 2. Guardia automática de la convención

- [x] 2.1 Añadir a `tests/agents/test_bundled_agents.py` un test que recorra
      `agents/` (incluyendo `subagents/` y `skills/` de cada agente) y falle
      si encuentra: un nombre de carpeta de agente/subagente/skill que no sea
      kebab-case en minúsculas, un archivo o carpeta dentro de la carpeta de
      un agente que no sea `agent.md`, `tool/`, `skills/` o `subagents/`, o
      una carpeta `subagents/` dentro de otra carpeta `subagents/`;
      verificación: `pytest tests/agents/test_bundled_agents.py -q` pasa en
      verde con el inventario actual y falla si se revierte temporalmente un
      nombre a, por ejemplo, `Viernes_v2` durante la prueba manual del test.
- [x] 2.2 Verificar que el nuevo test no introduce falsos positivos con
      `agents/jarvis/` (sin `skills/` ni `subagents/`) ni con
      `agents/viernes/subagents/investigador/` (sin `tool/tool.json`);
      verificación: `pytest tests/agents/test_bundled_agents.py -q` sigue en
      verde con ambos casos presentes.

## 3. Documentación de la convención para agentes futuros

- [ ] 3.1 Confirmar que `openspec/specs/agent-folder-convention/spec.md`
      queda disponible como referencia citable (tras el sync/archive de este
      cambio) para cualquier propuesta futura que añada un agente, subagente
      o skill; verificación: `openspec show agent-folder-convention --type
      spec --no-scenarios` devuelve la spec una vez archivado el cambio (paso
      de seguimiento, no de este cambio).
- [x] 3.2 Revisar que `design.md` (Decisiones D1-D4) queda como referencia
      explícita de por qué Tony no copia `dundun.json`, `prompts/` ni
      subagentes-enlace de DunDun, para que una propuesta futura que quiera
      adoptarlos sepa que debe proponer primero el cambio de loader
      correspondiente; verificación: lectura cruzada de `design.md` contra
      `specs/agent-folder-convention/spec.md` (Requirement "Patrones de
      DunDun no adoptados") confirma que ambos documentos son consistentes.

## Workflow follow-up

- Tras aprobar este cambio, archivarlo con `/opsx:archive` (o el flujo
  equivalente) para que `specs/agent-folder-convention/spec.md` se sincronice
  a `openspec/specs/agent-folder-convention/spec.md`.
- Si 1.5 encontró una desviación real y se movieron archivos, correr la
  suite completa (`pytest tests/agents/ tests/core/ -q`, o el comando de test
  del proyecto) antes de dar por cerrado el cambio.
