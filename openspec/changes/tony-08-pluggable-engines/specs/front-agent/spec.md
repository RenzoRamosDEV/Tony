# Spec Delta

## ADDED Requirements

### Requirement: Motor efectivo del `front` determina la implementación conversacional

La sesión conversacional del `front` SHALL usar la implementación de `ConversationRunner` correspondiente al motor efectivo del agente, manteniendo sin cambios el contrato de turno (`open`, `turn`, `interrupt`, `close`), el aislamiento del `worker` respecto al canal y los avisos de recarga en el canal, cualquiera que sea el motor.

#### Scenario: Front con motor `litellm`
- **WHEN** el `front` tiene `engine: litellm` y abre una sesión de chat
- **THEN** la sesión usa la implementación de `litellm` para cada turno y el resto del comportamiento conversacional (contexto dinámico, criterio de delegación, avisos de recarga) no cambia

#### Scenario: Cambio de motor no afecta a la delegación
- **WHEN** el `front` delega en el `worker` con `delegate`, cualquiera que sea el motor del `front`
- **THEN** el `worker` sigue sin recibir ninguna referencia al canal y el `TaskResult` solo llega al usuario a través de la respuesta redactada por el `front`
