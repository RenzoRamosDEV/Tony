# Spec Delta

## ADDED Requirements

### Requirement: Skills dentro de la carpeta del agente
Al cargar un agente, el sistema SHALL cargar cada `skills/<nombre>/SKILL.md` de su carpeta y exponer la lista de skills válidas y la lista de errores de las inválidas en la definición del agente. Una skill inválida SHALL NOT hacer fallar la carga del agente.

#### Scenario: Agente con skills
- **GIVEN** `agents/viernes/skills/resumen-web/SKILL.md` válida y `agents/viernes/skills/mala/SKILL.md` sin `description`
- **WHEN** se carga `viernes`
- **THEN** la definición tiene la skill `resumen-web`, un error de skill que nombra `mala`, y la carga no falla

### Requirement: Subagentes dentro de la carpeta del agente
Al cargar un agente, el sistema SHALL cargar cada `subagents/<nombre>/` como un agente (con su `agent.md`, `skills/` y `tool/tool.json`) y exponerlos por nombre en la definición del padre, junto con el error de cada subagente que no cargue. Un subagente roto SHALL NOT hacer fallar la carga del padre. Cada subagente SHALL conocer el nombre de su padre.

#### Scenario: Subagente válido
- **GIVEN** `agents/viernes/subagents/investigador/agent.md` con `name: investigador`, `role: worker`, `model: claude-sonnet` y sin `tool/tool.json`
- **WHEN** se carga `viernes`
- **THEN** `viernes` tiene el subagente `investigador` con configuración de tools vacía y padre `viernes`

#### Scenario: Subagente roto
- **GIVEN** `agents/viernes/subagents/roto/agent.md` con `role: helper`
- **WHEN** se carga `viernes`
- **THEN** `viernes` carga, no tiene el subagente `roto` y registra un error de subagente que nombra `roto` y `role`

#### Scenario: Subagente con rol front
- **GIVEN** `subagents/x/agent.md` con `role: front`
- **WHEN** se carga el padre
- **THEN** el subagente carga y se registra una advertencia que nombra `x` y los roles `front`/`worker`

### Requirement: Profundidad de carga de subagentes
Un subagente SHALL NOT cargar su propia carpeta `subagents/` y, si su `tool.json` declara `run_subagent` en `native`, el nombre SHALL eliminarse de la lista con una advertencia.

#### Scenario: Nivel 2 ignorado
- **GIVEN** `subagents/investigador/subagents/otro/agent.md` válido
- **WHEN** se carga el padre
- **THEN** `investigador` no tiene subagentes

#### Scenario: run_subagent eliminado del subagente
- **GIVEN** `subagents/investigador/tool/tool.json` con `native: ["run_subagent", "read_skill"]`
- **WHEN** se carga el padre
- **THEN** `native` del subagente es `["read_skill"]` y se registra una advertencia

### Requirement: Inventario tolerante con subagentes
La carga de todos los agentes de un directorio SHALL incluir, para cada agente cargado, sus subagentes y sus errores de subagentes y de skills, de modo que un inventario pueda mostrarlos sin volver a leer el disco.

#### Scenario: Inventario completo
- **GIVEN** `viernes` con el subagente `investigador` y `jarvis` sin subagentes
- **WHEN** se cargan todos los agentes
- **THEN** el resultado contiene `viernes` con `investigador` entre sus subagentes y `jarvis` con un mapa de subagentes vacío
