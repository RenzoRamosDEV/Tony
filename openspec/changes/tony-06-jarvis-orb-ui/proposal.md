# Proposal

## Why

La interfaz web actual es una columna de chat plana que no transmite la idea de "Jarvis". Se quiere una pieza central viva: un orbe holográfico dorado en 3D, rotable, que reaccione a lo que hace el asistente (escuchar, pensar, hablar) como en Iron Man, sin perder ninguna funcionalidad del chat ni de la voz.

## What Changes

- Nuevo orbe holográfico 3D a pantalla completa, generado proceduralmente (capas geodésicas, arcos, estrías radiales, nube de partículas, núcleo brillante) con resplandor aditivo ámbar sobre fondo casi negro.
- Interacción con el orbe: rotación por arrastre con inercia, zoom acotado, sin desplazamiento; autorrotación al quedar inactivo.
- Cuatro estados visuales (`idle`, `listening`, `thinking`, `speaking`) derivados del estado existente de la app; el nivel del micrófono y la amplitud real de la voz de Jarvis mueven el orbe, con transiciones suavizadas.
- Rendimiento y robustez: tope de densidad de píxeles, pausa con la pestaña oculta, liberación de recursos al desmontar, orbe estático en CSS cuando no hay WebGL y animación mínima con `prefers-reduced-motion`.
- Rediseño de la disposición en HUD: el chat pasa a una capa translúcida con subtítulos del último intercambio bajo el orbe y un cajón desplegable con la transcripción completa; barra HUD inferior con entrada, micrófono, selector de modo y "Detener audio"; confirmaciones como tarjeta HUD centrada; panel de debug como cajón lateral superpuesto.
- **BREAKING** (solo visual): la UI deja de seguir `prefers-color-scheme` y usa siempre un tema oscuro HUD; los avisos de nuevos mensajes por `aria-live` pasan a la región de subtítulos.
- La reproducción de voz expone su amplitud mediante un analizador intercalado, sin alterar el audio ni la cola sin huecos.
- Sin cambios en el protocolo WebSocket, la API HTTP ni el backend Python.

## Capabilities

### New Capabilities
- `web-ui-orb`: orbe holográfico 3D de la UI web: composición de la escena, interacción, estados visuales y su mapeo desde el estado de la app, reacción a audio, transiciones, movimiento reducido, rendimiento, liberación de recursos y alternativa sin WebGL.

### Modified Capabilities
- `web-ui-chat`: nueva disposición HUD superpuesta al orbe (barra inferior, subtítulos, cajón de transcripción), confirmación como tarjeta HUD centrada y tema oscuro fijo en "Accesibilidad y diseño"; el resto del comportamiento se mantiene.
- `web-ui-voice`: la reproducción expone la amplitud de salida para el orbe sin alterar la señal.
- `web-ui-debug-panel`: el panel plegable pasa a ser un cajón lateral superpuesto al orbe, conservando persistencia y contenido.

## Impact

- Código: `tony/apps/web/frontend/src` (`App.tsx`, `styles.css`, `audio/player.ts`, `audio/hooks.ts`, nuevos módulos del orbe y componentes HUD; ajustes en `ChatList`, `ConfirmationCard`, `DebugPanel` y sus pruebas, y en `styles.test.ts`).
- Dependencias nuevas del frontend: `three` y `@types/three` con versión exacta; ninguna dependencia de backend.
- `index.html`: `color-scheme` oscuro y carga opcional de fuentes HUD con alternativa del sistema.
- Tamaño del bundle mayor (Three.js); sin cambios en `uv run tony web`, que sigue sirviendo `dist` desde disco.
- Verificación visual con capturas de Playwright guardadas dentro del cambio.
