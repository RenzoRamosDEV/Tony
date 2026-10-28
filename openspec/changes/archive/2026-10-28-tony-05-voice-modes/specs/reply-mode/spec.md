# Spec Delta

## MODIFIED Requirements

### Requirement: Precedencia del modo efectivo
El modo efectivo SHALL resolverse en este orden: prefijo del mensaje > `reply_mode` de los ajustes persistidos > `reply_mode` de la configuración global. `auto` SHALL resolverse a `voice` si la entrada fue audio y a `text` si fue texto. El modo SHALL fijarse al aceptar cada mensaje y no cambiar durante el turno. El bloque dinámico del turno SHALL incluir `input_modality: voice|text` según la entrada fuera audio o texto, y un cambio hecho por frase con `set_reply_mode` SHALL reflejarse en el `effective_mode` del siguiente mensaje aceptado.

#### Scenario: Tabla de precedencia
- **GIVEN** las combinaciones (prefijo, ajustes, configuración, modalidad): (`/v`, `text`, `auto`, texto) → `voice`; (ninguno, `text`, `voice`, audio) → `text`; (ninguno, ausente, `both`, texto) → `both`; (ninguno, ausente, `auto`, texto) → `text`; (ninguno, ausente, `auto`, audio) → `voice`; (ninguno, `auto`, `text`, audio) → `voice`
- **WHEN** se resuelve cada combinación
- **THEN** se obtiene el modo indicado

#### Scenario: Cambio de ajustes durante un turno
- **GIVEN** un turno iniciado en `text`
- **WHEN** `set_reply_mode("voice")` se ejecuta durante ese mismo turno
- **THEN** la respuesta del turno sigue en `text` y el siguiente mensaje se resuelve a `voice`

#### Scenario: Modalidad de entrada en el bloque dinámico
- **GIVEN** un mensaje cuya entrada fue audio
- **WHEN** se construye el prompt del turno
- **THEN** el bloque dinámico contiene `Modalidad de entrada: voice`; para un mensaje escrito contiene `Modalidad de entrada: text`

#### Scenario: Cambio por frase reflejado en el siguiente mensaje
- **GIVEN** ajustes en `auto` y una entrada por audio resuelta a `voice`
- **WHEN** el `front` llama a `set_reply_mode("text")` en ese turno y llega otra entrada por audio
- **THEN** el segundo mensaje se acepta con `effective_mode: text`
