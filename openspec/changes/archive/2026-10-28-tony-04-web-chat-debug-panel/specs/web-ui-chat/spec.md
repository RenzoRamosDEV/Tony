# Spec Delta

## Purpose

Define la interfaz web de chat con Jarvis: lista de mensajes con markdown saneado y streaming, confirmaciones y cancelación por botón, entrada de texto, selector de modo de respuesta, estados de conexión y requisitos de accesibilidad y diseño.

## ADDED Requirements

### Requirement: Conexión y carga del historial
Al cargar, la UI SHALL abrir `/ws/chat`, enviar `hello` con el último `conversation_id` guardado en el navegador (o `null` si no hay) y, tras `hello.ok`, cargar el historial por `GET /api/conversations/{id}/messages`; un `unknown_conversation` SHALL provocar un `hello {conversation_id: null}` automático. La UI SHALL ofrecer un botón "Nueva conversación" que envía `hello {conversation_id: null}`.

#### Scenario: Primera carga
- **GIVEN** el navegador sin conversación guardada
- **WHEN** se abre la página
- **THEN** la UI envía `hello {conversation_id: null}`, guarda el `conversation_id` recibido y muestra el estado vacío

#### Scenario: Conversación guardada
- **GIVEN** el navegador con `conversation_id: "c-1"` guardado y dos mensajes en el historial
- **WHEN** se abre la página
- **THEN** la UI envía `hello {conversation_id: "c-1"}` y muestra los dos mensajes antes de aceptar entrada

### Requirement: Lista de mensajes con markdown saneado
La UI SHALL mostrar los mensajes de usuario y asistente diferenciados; el contenido del asistente SHALL renderizarse como markdown saneado: sin HTML crudo ni scripts, enlaces con `rel="noopener noreferrer"` y `target="_blank"`, y bloques de código preservados. El contenido del usuario SHALL mostrarse como texto plano.

#### Scenario: HTML crudo neutralizado
- **WHEN** llega `assistant.final` con `display_text: "Hola <img src=x onerror=alert(1)> **ok**"`
- **THEN** no se renderiza ninguna imagen ni se ejecuta script y `ok` aparece en negrita

#### Scenario: Enlace seguro
- **WHEN** llega `display_text: "[docs](https://example.com)"`
- **THEN** el enlace renderizado tiene `rel="noopener noreferrer"` y `target="_blank"`

#### Scenario: Texto del usuario literal
- **WHEN** el usuario envía `**no negrita** <b>x</b>`
- **THEN** su burbuja muestra ese texto literalmente

### Requirement: Streaming y burbuja de espera
Durante un turno la UI SHALL mostrar la respuesta en construcción concatenando los `assistant.delta` del mismo `message_id` y SHALL sustituir ese texto por `assistant.final.display_text` al llegar; `assistant.wait` SHALL mostrarse como una burbuja atenuada que desaparece con `assistant.final`. Mientras el turno está en curso la entrada SHALL quedar deshabilitada con un indicador visible.

#### Scenario: Deltas y final
- **WHEN** llegan `assistant.delta {text: "Hola"}`, `assistant.delta {text: ", Renzo"}` y `assistant.final {display_text: "Hola, Renzo."}`
- **THEN** la burbuja muestra sucesivamente `Hola`, `Hola, Renzo` y finalmente `Hola, Renzo.` sin duplicar texto

#### Scenario: Burbuja de espera
- **WHEN** llega `assistant.wait {text: "Dame un momento."}`
- **THEN** aparece una burbuja atenuada con ese texto que desaparece al llegar `assistant.final`

#### Scenario: Entrada bloqueada durante el turno
- **GIVEN** `user.accepted` recibido y sin `assistant.final`
- **WHEN** el usuario intenta enviar otro mensaje
- **THEN** el botón de enviar está deshabilitado y se muestra "Jarvis está respondiendo…"

### Requirement: Confirmación en línea con cuenta atrás
Al recibir `task.needs_confirmation`, la UI SHALL mostrar un bloque en línea con el nombre de la tool, los `args` formateados como JSON y los botones `Confirmar` y `Rechazar`, con una cuenta atrás desde `expires_in_s` (60 s). Pulsar un botón SHALL enviar `confirm {confirmation_id, approved}`; el bloque SHALL desaparecer al recibir `task.confirmed`, `task.cancelled`, `task.result` o al llegar la cuenta atrás a 0.

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

### Requirement: Cancelar tarea
Mientras exista una tarea activa (desde `task.queued` hasta `task.result`) la UI SHALL mostrar un botón `Cancelar tarea` que envía `cancel {task_id}` de la tarea raíz activa; el botón SHALL desaparecer al llegar `task.result`.

#### Scenario: Cancelación por botón
- **GIVEN** `task.running` recibido para `t-9`
- **WHEN** el usuario pulsa `Cancelar tarea`
- **THEN** se envía `cancel {task_id: "t-9"}` y el botón desaparece al llegar `task.result`

### Requirement: Entrada de texto
La entrada SHALL enviar con `Enter`, insertar un salto de línea con `Shift+Enter`, ignorar envíos en blanco y enviar los prefijos `/v`, `/t`, `/b` tal cual dentro de `user.text.text`. El campo SHALL mostrar el marcador "Escribe a Jarvis…" cuando esté vacío.

#### Scenario: Enter envía
- **WHEN** el usuario escribe `hola` y pulsa `Enter`
- **THEN** se envía `user.text {text: "hola"}` y el campo queda vacío

#### Scenario: Shift+Enter salta de línea
- **WHEN** el usuario pulsa `Shift+Enter`
- **THEN** el campo contiene un salto de línea y no se envía nada

#### Scenario: Prefijo literal
- **WHEN** el usuario envía `/v qué hora es`
- **THEN** se envía `user.text {text: "/v qué hora es"}` sin transformar

### Requirement: Selector de modo de respuesta
La UI SHALL mostrar un grupo de botones `auto | voice | text | both` que llama a `PATCH /api/settings` al pulsar, marca como activo el modo persistido (`hello.ok.reply_mode`, respuesta del `PATCH` y `GET /api/settings` tras cada `assistant.final`) y muestra junto a cada mensaje de usuario el `effective_mode` recibido en `user.accepted`. Un error del `PATCH` SHALL mostrar un aviso y restaurar el modo anterior.

#### Scenario: Cambio por botón
- **WHEN** el usuario pulsa `voice`
- **THEN** se llama a `PATCH /api/settings` con `{"reply_mode": "voice"}` y, con respuesta `200`, el botón `voice` queda activo

#### Scenario: Cambio hecho por frase
- **GIVEN** el botón `auto` activo
- **WHEN** Jarvis fija `text` por frase y llega `assistant.final`
- **THEN** la UI consulta `GET /api/settings` y marca `text` como activo

#### Scenario: PATCH fallido
- **GIVEN** el botón `text` activo
- **WHEN** el usuario pulsa `both` y el `PATCH` responde `422`
- **THEN** se muestra un aviso y `text` vuelve a estar activo

### Requirement: Estados de conexión y error
Sin conversación la UI SHALL mostrar el estado vacío "Escribe a Jarvis…"; si el socket se cierra SHALL mostrar un banner "Desconectado, reintentando…" y reconectar automáticamente cada 2 s enviando `hello {conversation_id, last_seq}`; los mensajes `error` del servidor SHALL mostrarse como aviso sin perder el historial. Un `hello.ok {resync: true}` SHALL recargar el historial por HTTP.

#### Scenario: Reconexión automática
- **GIVEN** el socket cerrado por el servidor
- **WHEN** pasan 2 s
- **THEN** la UI abre un socket nuevo y envía `hello {conversation_id, last_seq: <último seq visto>}`

#### Scenario: Error visible
- **WHEN** llega `error {code: "turn_in_progress", detail}`
- **THEN** se muestra un aviso con el detalle y los mensajes anteriores siguen visibles

#### Scenario: Resincronización
- **WHEN** llega `hello.ok {resync: true}`
- **THEN** la UI recarga `GET /api/conversations/{id}/messages` y descarta el texto en streaming anterior

### Requirement: Accesibilidad y diseño
La UI SHALL ser navegable por teclado con foco visible, todos los botones con icono SHALL tener `aria-label`, la lista de mensajes SHALL anunciar nuevos mensajes con `aria-live="polite"`, el contraste SHALL cumplir WCAG AA, la columna de chat SHALL limitarse a 80 caracteres (`max-width: 80ch`), el tema claro/oscuro SHALL seguir `prefers-color-scheme`, los iconos SHALL ser SVG inline (sin emojis) y todo el texto visible SHALL estar en español.

#### Scenario: Navegación por teclado
- **WHEN** el usuario recorre la página con `Tab`
- **THEN** alcanza la entrada, el botón de enviar, el selector de modo, los botones de confirmación y el panel de debug, con un anillo de foco visible en cada uno

#### Scenario: Modo oscuro automático
- **GIVEN** el sistema con `prefers-color-scheme: dark`
- **WHEN** se abre la página
- **THEN** se aplican los colores del tema oscuro sin interacción del usuario

#### Scenario: Botones con etiqueta
- **WHEN** se inspecciona el botón de enviar y el de plegar el panel
- **THEN** ambos tienen `aria-label` en español
