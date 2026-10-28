# Spec Delta

## ADDED Requirements

### Requirement: Disposición HUD sobre el orbe
La UI SHALL superponer al orbe una capa HUD translúcida (fondo difuminado, acentos ámbar, tipografía HUD con alternativa del sistema): arriba el título, "Nueva conversación" y el banner de estado; abajo una barra con la entrada de texto, el micrófono, el estado de voz con su nivel, el selector de modo, "Detener audio" y "Cancelar tarea". Todos los controles existentes SHALL conservar su comportamiento.

#### Scenario: Controles en la barra inferior
- **WHEN** se abre la página
- **THEN** la entrada, el botón de micrófono y el selector de modo aparecen en la barra inferior sobre el orbe y responden igual que antes

#### Scenario: Cancelar desde la HUD
- **GIVEN** `task.running` recibido para `t-9`
- **WHEN** el usuario pulsa `Cancelar tarea` en la barra inferior
- **THEN** se envía `cancel {task_id: "t-9"}`

### Requirement: Subtítulos del último intercambio
Bajo el orbe la UI SHALL mostrar como subtítulos el último mensaje del usuario y la última respuesta del asistente (en streaming, burbuja de espera o final, con el mismo markdown saneado), limitados en altura con desplazamiento interno; sin mensajes SHALL mostrar "Escribe a Jarvis…". La región SHALL anunciar los mensajes nuevos con `aria-live="polite"`.

#### Scenario: Respuesta en subtítulos
- **GIVEN** el usuario envió `hola`
- **WHEN** llegan `assistant.delta {text: "Hola"}` y `assistant.final {display_text: "Hola, Renzo."}`
- **THEN** los subtítulos muestran `hola` y después `Hola, Renzo.` sin duplicar texto

#### Scenario: Estado vacío en subtítulos
- **GIVEN** una conversación sin mensajes
- **WHEN** se abre la página
- **THEN** los subtítulos muestran "Escribe a Jarvis…"

### Requirement: Cajón de transcripción
La UI SHALL ofrecer un botón con `aria-label` y `aria-expanded` que despliega un cajón con la transcripción completa de la conversación (misma lista de mensajes, etiquetas de modo y markdown saneado), desplazado al último mensaje; plegado por defecto, se cierra con el botón o con `Escape` devolviendo el foco al botón.

#### Scenario: Abrir la transcripción
- **GIVEN** una conversación con cinco mensajes
- **WHEN** el usuario pulsa el botón de transcripción
- **THEN** el cajón muestra los cinco mensajes y el botón tiene `aria-expanded="true"`

#### Scenario: Cerrar con Escape
- **GIVEN** el cajón de transcripción abierto
- **WHEN** el usuario pulsa `Escape`
- **THEN** el cajón se pliega y el foco vuelve al botón de transcripción

## MODIFIED Requirements

### Requirement: Confirmación en línea con cuenta atrás
Al recibir `task.needs_confirmation`, la UI SHALL mostrar una tarjeta HUD centrada sobre el orbe con el nombre de la tool, los `args` formateados como JSON y los botones `Confirmar` y `Rechazar`, con una cuenta atrás desde `expires_in_s` (60 s). Pulsar un botón SHALL enviar `confirm {confirmation_id, approved}`; la tarjeta SHALL desaparecer al recibir `task.confirmed`, `task.cancelled`, `task.result` o al llegar la cuenta atrás a 0.

#### Scenario: Confirmar por botón
- **GIVEN** un bloque de confirmación visible para `filesystem.move_file`
- **WHEN** el usuario pulsa `Confirmar`
- **THEN** se envía `confirm {confirmation_id, approved: true}` y, al llegar `task.confirmed`, el bloque desaparece

#### Scenario: Caducidad
- **GIVEN** un bloque de confirmación con `expires_in_s: 60`
- **WHEN** pasan 60 s sin pulsar nada
- **THEN** el bloque desaparece y se muestra un aviso "Confirmación caducada"

#### Scenario: Reconexión con confirmación pendiente
- **WHEN** llega `hello.ok` con `pending_confirmation` y `expires_in_s: 39`
- **THEN** se muestra el bloque con la cuenta atrás desde 39

#### Scenario: Tarjeta centrada
- **WHEN** llega `task.needs_confirmation`
- **THEN** la tarjeta aparece centrada sobre el orbe y el foco pasa al botón `Rechazar`

### Requirement: Accesibilidad y diseño
La UI SHALL ser navegable por teclado con foco visible, todos los botones con icono SHALL tener `aria-label`, los mensajes nuevos SHALL anunciarse con `aria-live="polite"` en la región de subtítulos, el texto SHALL cumplir contraste WCAG AA sobre la HUD, subtítulos y transcripción SHALL limitarse a 80 caracteres (`max-width: 80ch`), el tema SHALL ser siempre oscuro HUD (`color-scheme: dark`), los iconos SHALL ser SVG inline (sin emojis) y todo el texto visible SHALL estar en español.

#### Scenario: Navegación por teclado
- **WHEN** el usuario recorre la página con `Tab`
- **THEN** alcanza la entrada, el botón de enviar, el selector de modo, los botones de confirmación y el panel de debug, con un anillo de foco visible en cada uno

#### Scenario: Modo oscuro automático
- **GIVEN** el sistema con `prefers-color-scheme: dark`
- **WHEN** se abre la página
- **THEN** se aplican los colores del tema oscuro sin interacción del usuario

#### Scenario: Tema HUD fijo
- **GIVEN** el sistema con `prefers-color-scheme: light`
- **WHEN** se abre la página
- **THEN** se aplica el tema oscuro HUD y el texto mantiene contraste AA

#### Scenario: Botones con etiqueta
- **WHEN** se inspecciona el botón de enviar y el de plegar el panel
- **THEN** ambos tienen `aria-label` en español
