# Spec Delta

## Purpose

Define cómo arranca y se protege el servidor web local de Tony (`tony web`): dirección de escucha, política de `Origin`, límites de tamaño y de cola, servicio del frontend compilado y ciclo de vida de la sesión de chat que el servidor expone.

## ADDED Requirements

### Requirement: Comando `tony web`
El sistema SHALL ofrecer `tony web [--port] [--host] [--open] [--allow-remote] [--config PATH] [--agents-dir PATH]` que carga la configuración y los agentes por rol como `tony chat` y arranca un servidor HTTP/WebSocket. `--port` y `--host` SHALL tomar por defecto `web.port` (8787) y `web.host` (`127.0.0.1`) de la configuración global; con `--open` SHALL abrir `http://<host>:<port>/` en el navegador tras arrancar.

#### Scenario: Arranque por defecto
- **GIVEN** la configuración global sin sección `web`
- **WHEN** se ejecuta `tony web`
- **THEN** el servidor escucha en `127.0.0.1:8787` y `GET http://127.0.0.1:8787/api/health` responde `200`

#### Scenario: Puerto por opción
- **WHEN** se ejecuta `tony web --port 9000`
- **THEN** el servidor escucha en `127.0.0.1:9000`

#### Scenario: Extra no instalado
- **GIVEN** el extra `tony[web]` no está instalado
- **WHEN** se ejecuta `tony web`
- **THEN** termina con código `2` y un mensaje en español que indica instalar `tony[web]`

#### Scenario: Agente inexistente
- **GIVEN** `front: nadie` en la configuración
- **WHEN** se ejecuta `tony web`
- **THEN** termina con código `2` y un mensaje en español que nombra `nadie`, sin abrir ningún puerto

### Requirement: Escucha solo en loopback salvo autorización explícita
Un `--host` distinto de `127.0.0.1`, `localhost` o `::1` SHALL rechazarse con código `2` salvo que se indique `--allow-remote`; con `--allow-remote` el servidor SHALL arrancar e imprimir en `stderr` una advertencia en español de que escucha fuera de loopback sin autenticación ni HTTPS.

#### Scenario: Host remoto sin autorización
- **WHEN** se ejecuta `tony web --host 0.0.0.0`
- **THEN** termina con código `2` y un mensaje que nombra `--allow-remote`, sin abrir ningún puerto

#### Scenario: Host remoto autorizado
- **WHEN** se ejecuta `tony web --host 0.0.0.0 --allow-remote`
- **THEN** el servidor arranca y `stderr` contiene una advertencia que menciona `0.0.0.0`

### Requirement: Validación de `Origin`
Toda petición HTTP mutante (`POST`, `PATCH`, `PUT`, `DELETE`) y todo intento de conexión WebSocket SHALL traer una cabecera `Origin` igual a `http://<host>:<port>` o `http://localhost:<port>` (y `http://127.0.0.1:<port>` cuando `host` es `localhost`); en caso contrario el servidor SHALL responder `403` con `{error: "forbidden_origin", detail}` y, en el WebSocket, cerrar antes de aceptar ningún mensaje. Las peticiones `GET` sin `Origin` SHALL aceptarse.

#### Scenario: Origin inválido en WebSocket
- **GIVEN** el servidor en `127.0.0.1:8787`
- **WHEN** una página en `http://evil.local` abre `ws://127.0.0.1:8787/ws/chat`
- **THEN** la conexión se cierra con `403` antes de aceptar el `hello`

#### Scenario: Origin inválido en PATCH
- **WHEN** llega `PATCH /api/settings` con `Origin: http://evil.local`
- **THEN** la respuesta es `403` con `{error: "forbidden_origin", detail}` y los ajustes no cambian

#### Scenario: Mutación sin Origin
- **WHEN** llega `POST /api/tasks/t1/cancel` sin cabecera `Origin`
- **THEN** la respuesta es `403` y la tarea no se cancela

#### Scenario: GET sin Origin
- **WHEN** llega `GET /api/health` sin cabecera `Origin` (por ejemplo desde `curl`)
- **THEN** la respuesta es `200`

#### Scenario: Origin localhost equivalente
- **GIVEN** el servidor en `127.0.0.1:8787`
- **WHEN** llega `PATCH /api/settings` con `Origin: http://localhost:8787`
- **THEN** la petición se acepta

### Requirement: Límite de tamaño de mensaje WebSocket
Un mensaje de texto WebSocket mayor de 32 KiB (32 768 bytes en UTF-8) SHALL rechazarse con `error {code: "message_too_large", detail}` y el cierre de la conexión con código `1009`, sin procesarlo.

#### Scenario: Mensaje demasiado grande
- **WHEN** el cliente envía un `user.text` cuyo sobre JSON ocupa 40 000 bytes
- **THEN** recibe `error {code: "message_too_large"}`, la conexión se cierra con `1009` y no se crea ningún mensaje de usuario

#### Scenario: Mensaje en el límite
- **WHEN** el cliente envía un sobre JSON de exactamente 32 768 bytes
- **THEN** el mensaje se procesa con normalidad

### Requirement: Cola de salida acotada por cliente
La cola de eventos pendientes de envío a cada socket SHALL estar acotada a 500 eventos. Cuando esté llena, el servidor SHALL fusionar los `assistant.delta` pendientes del mismo `message_id` en un único `assistant.delta` con el texto concatenado antes de encolar el siguiente evento, y nunca SHALL descartar eventos de otro tipo ni cerrar la conversación.

#### Scenario: Cola llena con deltas
- **GIVEN** un socket que no lee y 500 eventos encolados, 400 de ellos `assistant.delta` del mismo mensaje
- **WHEN** llega un nuevo evento
- **THEN** los 400 deltas se sustituyen por uno con su texto concatenado, el nuevo evento se encola y los `task.*` encolados se conservan en orden

#### Scenario: Texto final siempre completo
- **GIVEN** deltas fusionados o descartados por la cola
- **WHEN** termina el turno
- **THEN** `assistant.final.display_text` contiene el texto completo de la respuesta

### Requirement: Servicio del frontend compilado
`GET /` SHALL servir `index.html` del frontend compilado y `GET /assets/*` sus ficheros estáticos. Si el frontend no está compilado, `GET /` SHALL responder `200` con una página HTML mínima en español que indica el comando de compilación (`cd tony/apps/web/frontend && npm install && npm run build`).

#### Scenario: Frontend compilado
- **GIVEN** existe `tony/apps/web/frontend/dist/index.html`
- **WHEN** llega `GET /`
- **THEN** la respuesta es `200` con ese `index.html` y `Content-Type: text/html`

#### Scenario: Frontend sin compilar
- **GIVEN** no existe el directorio `dist`
- **WHEN** llega `GET /`
- **THEN** la respuesta es `200`, HTML, y contiene `npm run build`

### Requirement: Una sesión de chat abierta por servidor
El servidor SHALL mantener como máximo una sesión de chat abierta (una conversación con su sesión del `front` y el orquestador compartido). Un `hello` para otra conversación SHALL cerrar la sesión actual y abrir la nueva solo si la actual no tiene socket conectado, turno en curso ni tarea activa; de lo contrario SHALL responder `error {code: "conversation_busy", detail}`.

#### Scenario: Cambio de conversación en reposo
- **GIVEN** la conversación `c1` abierta sin socket ni tarea activa
- **WHEN** un cliente envía `hello {conversation_id: "c2"}`
- **THEN** la sesión de `c1` se cierra, `c2` se abre y el cliente recibe `hello.ok {conversation_id: "c2"}`

#### Scenario: Cambio de conversación con tarea en curso
- **GIVEN** la conversación `c1` con una tarea en `running` y su socket desconectado
- **WHEN** otro cliente envía `hello {conversation_id: "c2"}`
- **THEN** recibe `error {code: "conversation_busy"}` y `c1` sigue abierta

### Requirement: Cierre ordenado
Al recibir `SIGINT`/`SIGTERM` el servidor SHALL dejar de aceptar conexiones, cerrar los sockets abiertos con código `1001`, cancelar las tareas activas, cerrar la sesión del `front`, el orquestador, el observador de configuración y el log de la sesión, y terminar con código `0` en menos de 10 s.

#### Scenario: Ctrl+C con tarea activa
- **GIVEN** un socket conectado y una tarea en `running`
- **WHEN** el proceso recibe `SIGINT`
- **THEN** el socket se cierra con `1001`, la tarea termina en `cancelled` y el proceso sale con código `0`
