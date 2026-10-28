# Spec Delta

## MODIFIED Requirements

### Requirement: Contexto dinámico del turno
En cada turno, el prompt efectivo del `front` SHALL incluir el cuerpo de `agent.md` más la fecha y hora local con zona, el modo de respuesta efectivo con su `style`, el bloque de preferencias del usuario (releído del fichero en ese turno), el catálogo de tools nativas disponibles, el índice de skills del `front` (solo nombre y descripción) y, antes del texto del usuario, los bloques `<skill name="…">…</skill>` de las skills cuyo `trigger` coincide con ese texto.

#### Scenario: Preferencia editada a mano
- **GIVEN** una sesión abierta y el usuario añade a mano la línea `- [2026-10-28] Prefiere respuestas cortas` a `memory/preferences.md`
- **WHEN** envía el siguiente mensaje sin reiniciar
- **THEN** el prompt de ese turno contiene `Prefiere respuestas cortas`

#### Scenario: Modo y estilo del turno
- **GIVEN** `style.voice = "Frases cortas, sin markdown"` y un turno con modo efectivo `voice`
- **WHEN** se construye el prompt del turno
- **THEN** contiene `voice` como modo efectivo y la instrucción `Frases cortas, sin markdown`

#### Scenario: Índice de skills del front
- **GIVEN** un `front` con la skill `protocolo-mañana` (descripción `Briefing de la mañana`)
- **WHEN** se construye el system prompt de la sesión
- **THEN** contiene `Skills disponibles:` y `- protocolo-mañana: Briefing de la mañana`, y no contiene el cuerpo de la skill

#### Scenario: Skill activada en el turno
- **GIVEN** un `front` con la skill `protocolo-mañana` (trigger `buenos días`)
- **WHEN** el usuario escribe `Buenos días, Jarvis`
- **THEN** el prompt del turno contiene el bloque `<skill name="protocolo-mañana">` entre el preámbulo y el texto del usuario

### Requirement: Tools nativas del servidor `tony`
Las tools nativas SHALL exponerse en el servidor MCP en proceso `tony` (`mcp__tony__<nombre>`) y SHALL ser exactamente las listadas en `tool.json.native` del agente de entre `delegate`, `remember`, `set_reply_mode` y `read_skill`; `run_subagent` SHALL NOT exponerse al `front` aunque se declare, con una advertencia. `delegate(objetivo, contexto="", restricciones=[])` SHALL enviar la tarea al orquestador y esperar su `TaskResult` sin el límite de 20 s de las tools MCP (solo el de la tarea), devolviéndolo serializado.

#### Scenario: Catálogo nativo según tool.json
- **GIVEN** `native: ["remember"]`
- **WHEN** se construye el servidor `tony`
- **THEN** expone `remember` y no expone `delegate` ni `set_reply_mode`

#### Scenario: read_skill en el front
- **GIVEN** `native: ["delegate", "read_skill"]` y la skill `protocolo-mañana`
- **WHEN** el modelo llama a `read_skill("protocolo-mañana")`
- **THEN** recibe el cuerpo de la skill

#### Scenario: run_subagent ignorado en el front
- **GIVEN** `native: ["delegate", "run_subagent"]`
- **WHEN** se construye el servidor `tony`
- **THEN** expone `delegate`, no expone `run_subagent` y se registra una advertencia

#### Scenario: Delegate devuelve el resultado
- **GIVEN** el `front` llama a `delegate("lista los .md de ~/notas")`
- **WHEN** la tarea termina con `{status: "ok", resumen: "3 ficheros", datos: ["a.md", "b.md", "c.md"], pasos: [...], errores: []}`
- **THEN** el modelo recibe ese `TaskResult` serializado como JSON

#### Scenario: Delegate sin límite de 20 s
- **GIVEN** `tool_timeout_s = 1` y una tarea delegada que tarda 2 s
- **WHEN** el `front` llama a `delegate`
- **THEN** la llamada espera los 2 s y devuelve el resultado, sin error de timeout

#### Scenario: Delegate con cola llena
- **GIVEN** la cola del orquestador está llena
- **WHEN** el `front` llama a `delegate`
- **THEN** recibe `{status: "error", resumen: ..., errores: ["queue_full"]}` sin excepción

## ADDED Requirements

### Requirement: Avisos de recarga en el canal
Mientras una sesión de chat está abierta, cada evento `config.reloaded` o `config.reload_failed` SHALL reenviarse al canal como aviso en español que nombra al agente y, según el caso, los servidores o el error, sin interrumpir el turno en curso.

#### Scenario: Recarga notificada
- **GIVEN** una sesión de chat abierta
- **WHEN** se recarga `viernes` con los servidores `filesystem` y `fetch`
- **THEN** el canal recibe un aviso que contiene `viernes`, `filesystem` y `fetch`
