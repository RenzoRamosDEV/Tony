# Spec Delta

## MODIFIED Requirements

### Requirement: Panel lateral plegable
La UI SHALL mostrar el panel de debug como un cajón lateral superpuesto al orbe desde el borde derecho, sin redimensionar el orbe, con un botón de alternancia (con `aria-label` y `aria-expanded`); el estado plegado/desplegado SHALL conservarse en el navegador entre recargas y el panel SHALL mostrar la tarea raíz actual o, si no hay ninguna activa, la última terminada de la conversación.

#### Scenario: Plegado persistente
- **GIVEN** el panel plegado por el usuario
- **WHEN** se recarga la página
- **THEN** el panel sigue plegado y el botón tiene `aria-expanded="false"`

#### Scenario: Última tarea
- **GIVEN** la tarea `t-9` terminada y ninguna activa
- **WHEN** se abre el panel
- **THEN** muestra `t-9` con su estado final

#### Scenario: Cajón superpuesto
- **GIVEN** el panel plegado
- **WHEN** el usuario lo despliega
- **THEN** el cajón aparece sobre el lado derecho con fondo translúcido y el lienzo del orbe conserva su tamaño
