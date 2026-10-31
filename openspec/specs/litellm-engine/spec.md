# litellm-engine Specification

## Purpose
Define cómo un agente con `engine: litellm` ejecuta tareas y conversaciones contra cualquier proveedor compatible con LiteLLM usando una clave de API, con un bucle de llamada a herramientas propio sobre la misma barrera de ejecución que los demás motores.

## Requirements

### Requirement: Bucle de llamada a herramientas en proceso

Un agente con `engine: litellm` SHALL dirigir su propio bucle de turnos contra `litellm.acompletion`, traduciendo cada tool del catálogo a un tool estilo OpenAI (`type: function`) a partir de su esquema de entrada, hasta un turno sin llamadas a herramientas o hasta `max_steps` del agente.

#### Scenario: Traducción del catálogo a tools estilo OpenAI
- **WHEN** el agente abre una tarea o turno con un catálogo de tools MCP
- **THEN** cada tool se traduce a `{type: "function", function: {name, description, parameters}}` a partir de su esquema de entrada antes de la primera llamada a `litellm.acompletion`

#### Scenario: Turno con una llamada a herramienta
- **WHEN** el modelo responde con una llamada a una tool del catálogo
- **THEN** el motor ejecuta esa tool a través de la barrera, añade su resultado como mensaje `role: "tool"` y vuelve a llamar al modelo

#### Scenario: Límite de pasos alcanzado
- **WHEN** el bucle llega a `max_steps` turnos sin una respuesta final sin llamadas a herramientas
- **THEN** la tarea SHALL terminar con `status: "error"` y un mensaje en `errores` que indica el límite alcanzado

### Requirement: Salida estructurada con fallback

El motor `litellm` SHALL pedir la salida estructurada final vía `response_format={"type": "json_schema", ...}` con el esquema de `TaskResult` o `FrontReply` según el rol del agente. Cuando el modelo o proveedor configurado no soporta ese modo, el motor SHALL aceptar la respuesta de texto final y SHALL intentar extraer un JSON válido del texto como mejor esfuerzo; si no lo logra, SHALL devolver el texto completo como `resumen`/`text` con `status: "ok"` sin datos estructurados.

#### Scenario: Proveedor con soporte de `json_schema`
- **WHEN** el perfil `litellm` resuelve a un modelo que soporta `response_format` de tipo `json_schema`
- **THEN** la respuesta final SHALL validarse contra el esquema correspondiente antes de convertirse en el resultado de la tarea

#### Scenario: Proveedor sin soporte de `json_schema`
- **WHEN** el perfil `litellm` resuelve a un modelo sin soporte de `response_format` de tipo `json_schema`
- **THEN** el motor extrae el mejor JSON posible del texto final, y si no encuentra ninguno, devuelve el texto completo como resultado sin fallar la tarea solo por eso

### Requirement: Resolución de clave de proveedor

El motor `litellm` SHALL resolver la clave de API del proveedor a partir de la variable de entorno que LiteLLM espera para el modelo del perfil (por ejemplo `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`), leída de `config/.env` o del entorno del proceso, sin requerir un campo nuevo en `agent.md`.

#### Scenario: Clave ausente
- **WHEN** el perfil `litellm` resuelve a un modelo de un proveedor cuya variable de entorno de clave no está definida
- **THEN** la tarea SHALL fallar con `status: "error"` y un mensaje en `errores` que nombra la variable de entorno esperada, antes de intentar la llamada al proveedor

### Requirement: Streaming de voz degradado

Un `front` con `engine: litellm` SHALL NOT emitir fragmentos parciales de `on_speech` durante el turno; el texto de voz SHALL entregarse completo una vez recibida la respuesta final del turno.

#### Scenario: Turno con reproducción de voz activa
- **WHEN** el canal activo usa voz y el front usa `engine: litellm`
- **THEN** la síntesis de voz comienza solo cuando el turno termina, no durante la generación

### Requirement: Comprobación de `tony doctor` para perfiles `litellm`

`tony doctor` SHALL comprobar, para cada perfil `litellm` en uso por algún agente, que la variable de entorno de clave que su modelo requiere está definida en `config/.env` o en el entorno; un fallo SHALL reportarse como `✗` nombrando la variable esperada, sin bloquear las demás comprobaciones.

#### Scenario: Clave de proveedor definida
- **WHEN** el perfil `litellm` en uso resuelve a un modelo cuya variable de clave está definida
- **THEN** `tony doctor` reporta `✓ litellm/<perfil>: clave presente`
