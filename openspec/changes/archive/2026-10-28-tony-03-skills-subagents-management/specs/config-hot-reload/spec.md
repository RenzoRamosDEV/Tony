# Spec Delta

## Purpose

Define la recarga en caliente de la configuración de tools de los agentes que ejecuta el orquestador: qué ficheros se observan, cómo se valida un cambio, cómo conviven las generaciones de servidores MCP y qué eventos se emiten.

## ADDED Requirements

### Requirement: Observación de `tool.json`
Mientras `tony chat` (o el servidor web) está en marcha, el sistema SHALL observar `agents/**/tool/tool.json` y reaccionar a cada escritura o creación recargando la configuración del agente afectado (un cambio en `subagents/<x>/tool/tool.json` SHALL recargar al agente padre). `agent.md`, `tony.yaml` y cualquier otro fichero SHALL NOT observarse. `tony run` SHALL NOT observar nada.

#### Scenario: Cambio en el tool.json del worker
- **GIVEN** `tony chat` en marcha con `viernes` cargado
- **WHEN** se guarda `agents/viernes/tool/tool.json`
- **THEN** se inicia una recarga de `viernes`

#### Scenario: Cambio en un subagente
- **WHEN** se guarda `agents/viernes/subagents/investigador/tool/tool.json`
- **THEN** se inicia una recarga de `viernes`

#### Scenario: Cambio en agent.md ignorado
- **WHEN** se guarda `agents/viernes/agent.md`
- **THEN** no se inicia ninguna recarga ni se emite ningún evento

### Requirement: Validación antes de aplicar
Cada recarga SHALL validar la configuración con las mismas comprobaciones que `tony config validate` para ese agente. Si la validación falla, SHALL conservarse la última configuración válida y emitirse `config.reload_failed {agent, error}`; las tareas nuevas SHALL seguir usando la generación anterior.

#### Scenario: Hot reload con JSON inválido
- **GIVEN** `tony chat` en marcha con `viernes` cargado
- **WHEN** se guarda `agents/viernes/tool/tool.json` con JSON mal formado
- **THEN** se emite `config.reload_failed {agent: "viernes", error: <mensaje>}`, la generación anterior sigue activa y la siguiente tarea funciona con ella

#### Scenario: Variable sin definir
- **WHEN** se guarda un `tool.json` con `${NO_EXISTE}`
- **THEN** se emite `config.reload_failed` cuyo `error` nombra `NO_EXISTE` y la generación anterior sigue activa

### Requirement: Generaciones de servidores MCP
Una recarga válida SHALL arrancar una nueva generación de servidores MCP del agente; las tareas en curso SHALL seguir usando su generación; las tareas que empiecen después SHALL usar la nueva; la generación antigua SHALL cerrarse cuando no quede ninguna tarea usándola. Al terminar el arranque SHALL emitirse `config.reloaded {agent, servers}` con los nombres de los servidores de la nueva generación.

#### Scenario: Tarea nueva usa la generación nueva
- **GIVEN** `viernes` con el servidor `fake` y una tarea `t1` en `running`
- **WHEN** se añade el servidor `fake2` a `tool.json` y, tras `config.reloaded {agent: "viernes", servers: ["fake", "fake2"]}`, se envía `t2`
- **THEN** `t2` ve `fake2` en su catálogo y `t1` no

#### Scenario: Generación antigua se cierra al liberar
- **GIVEN** `t1` en `running` con la generación `g1` y `g2` ya activa
- **WHEN** `t1` termina
- **THEN** los servidores de `g1` se paran y los de `g2` siguen activos

#### Scenario: Sin tareas en curso
- **GIVEN** ninguna tarea en `running`
- **WHEN** se completa una recarga válida
- **THEN** la generación anterior se cierra inmediatamente después de arrancar la nueva

#### Scenario: Servidor caído en la nueva generación
- **WHEN** la nueva configuración declara un servidor que no arranca
- **THEN** la generación nueva se activa igualmente con ese servidor en estado `error`, como en el arranque normal, y `config.reloaded` lista todos los servidores declarados

### Requirement: Eventos de recarga
`config.reloaded` y `config.reload_failed` SHALL registrarse en el log JSONL de la sesión de chat y SHALL notificarse al canal como aviso en español.

#### Scenario: Aviso en el canal
- **WHEN** se emite `config.reloaded {agent: "viernes", servers: ["filesystem", "fetch"]}`
- **THEN** el canal recibe un aviso que contiene `viernes`, `filesystem` y `fetch`, y el log de la sesión contiene el evento

#### Scenario: Aviso de fallo
- **WHEN** se emite `config.reload_failed {agent: "viernes", error: "tool.json inválido: …"}`
- **THEN** el canal recibe un aviso que contiene `viernes` y el error
