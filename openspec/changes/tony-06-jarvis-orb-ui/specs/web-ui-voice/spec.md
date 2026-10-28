# Spec Delta

## ADDED Requirements

### Requirement: Amplitud de la reproducción para el orbe
La reproducción SHALL pasar por un analizador de amplitud intercalado antes de la salida que no altere la señal, el orden ni la cola sin huecos, y SHALL exponer la amplitud actual normalizada entre 0 y 1; sin audio sonando, o tras `tts.cancelled` o "Detener audio", la amplitud SHALL ser 0. El nivel de entrada del micrófono SHALL exponerse igualmente al orbe.

#### Scenario: Amplitud durante la voz
- **GIVEN** un `tts.chunk` con voz sonando
- **WHEN** el orbe consulta la amplitud
- **THEN** obtiene un valor mayor que 0 y no mayor que 1, y el buffer sigue programado donde terminó el anterior

#### Scenario: Amplitud tras detener
- **GIVEN** audio en reproducción
- **WHEN** el usuario pulsa "Detener audio"
- **THEN** la amplitud expuesta es 0

#### Scenario: Pruebas sin hardware del analizador
- **WHEN** se ejecuta `npm test` con un `AudioContext` simulado
- **THEN** las pruebas comprueban que cada fuente se conecta al analizador y este a la salida
