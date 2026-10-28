# Spec Delta

## Purpose

Define el canal de línea de comandos `tony chat`: el bucle conversacional con el agente `front`, sus comandos locales, cómo muestra respuestas, progreso y confirmaciones, cómo cancela y cómo persiste la conversación.

## ADDED Requirements

### Requirement: Comando `tony chat`
El sistema SHALL ofrecer `tony chat [--config PATH] [--agents-dir PATH] [--new]` que carga la configuración, el agente `front` y el `worker` por rol, abre o continúa una conversación y muestra el prompt `tú> ` en un bucle hasta `/salir` o fin de entrada. Sin `--new` SHALL continuar la última conversación del canal `cli`; con `--new` SHALL crear una nueva.

#### Scenario: Continuar la última conversación
- **GIVEN** una conversación previa del canal `cli` con id `c1`
- **WHEN** se ejecuta `tony chat`
- **THEN** los mensajes nuevos se guardan en `c1`

#### Scenario: Nueva conversación
- **GIVEN** una conversación previa `c1`
- **WHEN** se ejecuta `tony chat --new`
- **THEN** se crea una conversación distinta y `c1` no recibe mensajes

#### Scenario: Rutas alternativas
- **WHEN** se ejecuta `tony chat --agents-dir /tmp/agentes --config /tmp/tony.yaml`
- **THEN** el `front` y la configuración se cargan desde esas rutas

#### Scenario: Front con rol discrepante
- **GIVEN** `front: viernes` y `agents/viernes/agent.md` con `role: worker`
- **WHEN** arranca `tony chat`
- **THEN** imprime en `stderr` una advertencia que nombra `viernes` y los roles `worker`/`front`, y la sesión continúa con `viernes`

#### Scenario: Agente inexistente
- **GIVEN** `front: nadie`
- **WHEN** arranca `tony chat`
- **THEN** termina con código `2` y un mensaje en español que nombra `nadie`

### Requirement: Presentación de la respuesta
Cada respuesta SHALL imprimirse al terminar el turno. En modo `text` SHALL imprimirse `display_text`. En `voice` y `both` SHALL imprimirse primero `🔊 <speech_text>` y después `display_text` completo. El texto del usuario, los prompts y los avisos SHALL ir a `stderr`; las respuestas a `stdout`.

#### Scenario: Modo text
- **GIVEN** modo efectivo `text` y respuesta `{display_text: "Hola", speech_text: null}`
- **WHEN** termina el turno
- **THEN** `stdout` contiene `Hola` y no contiene `🔊`

#### Scenario: Modo voice degradado a texto
- **GIVEN** modo efectivo `voice` y respuesta `{display_text: "# Informe\n...", speech_text: "Informe listo"}`
- **WHEN** termina el turno
- **THEN** `stdout` contiene la línea `🔊 Informe listo` seguida de `# Informe`

### Requirement: Progreso y frase de espera
Mientras una tarea delegada sigue, cada `task.progress` SHALL mostrarse como una línea tenue `· <tool>` y `assistant.wait` SHALL mostrarse como texto del asistente, ambos en `stderr`.

#### Scenario: Línea de progreso
- **WHEN** el canal recibe `task.progress {tool: "filesystem.read_file", step: 1}`
- **THEN** `stderr` contiene `· filesystem.read_file`

### Requirement: Confirmación interactiva en `tony chat`
Al recibir `task.needs_confirmation`, la CLI SHALL mostrar en `stderr` `<Worker> quiere ejecutar <tool> <args JSON>. ¿Confirmas? [s/N]` y SHALL enviar al orquestador `confirm(confirmation_id, approved)` con `approved = true` solo para `s`, `si` o `sí` (sin distinguir mayúsculas). Sin respuesta en `limits.confirm_timeout_s` SHALL informar de la cancelación.

#### Scenario: Aprobación
- **GIVEN** `task.needs_confirmation {confirmation_id: "c1", tool: "filesystem.move_file", args: {...}}`
- **WHEN** el usuario responde `Sí`
- **THEN** se llama a `confirm("c1", true)`

#### Scenario: Rechazo
- **WHEN** el usuario responde `n` o Intro vacío
- **THEN** se llama a `confirm("c1", false)`

#### Scenario: Sin respuesta
- **GIVEN** `confirm_timeout_s = 0.1`
- **WHEN** el usuario no responde
- **THEN** `stderr` informa de que la tarea se canceló por falta de confirmación y la sesión sigue aceptando mensajes

### Requirement: Comandos locales
La CLI SHALL atender sin llamar al `front`: `/mode` (muestra el modo persistido o, si no hay, el de configuración), `/mode auto|voice|text|both` (persiste el modo y lo confirma), `/memoria` (imprime el fichero de preferencias completo), `/cancel` (cancela la tarea activa) y `/salir` (termina). Un comando desconocido SHALL producir un aviso y no un turno.

#### Scenario: Mostrar modo
- **GIVEN** ajustes con `reply_mode: text`
- **WHEN** el usuario escribe `/mode`
- **THEN** la salida contiene `text` y no se ejecuta ningún turno

#### Scenario: Cambiar modo
- **WHEN** el usuario escribe `/mode voice`
- **THEN** `memory/settings.json` contiene `{"reply_mode": "voice"}` y la salida lo confirma

#### Scenario: Modo inválido
- **WHEN** el usuario escribe `/mode loud`
- **THEN** la salida lista `auto`, `voice`, `text`, `both` y los ajustes no cambian

#### Scenario: Memoria
- **GIVEN** el fichero de preferencias contiene dos líneas
- **WHEN** el usuario escribe `/memoria`
- **THEN** `stdout` contiene las dos líneas

#### Scenario: Salir
- **WHEN** el usuario escribe `/salir`
- **THEN** el proceso termina con código `0` y la sesión del `front` se cierra

### Requirement: Cancelación con `Ctrl+C`
Durante una tarea delegada, un `Ctrl+C` SHALL cancelar la tarea activa (motivo `user`) y mantener la sesión; un segundo `Ctrl+C` SHALL terminar el proceso ordenadamente. Fuera de una tarea, `Ctrl+C` SHALL terminar el proceso. Un lector de `stdin` bloqueado SHALL NOT impedir la salida del proceso.

#### Scenario: Primer Ctrl+C
- **GIVEN** una tarea delegada en curso
- **WHEN** llega `Ctrl+C`
- **THEN** se llama a `cancel(task_id, "user")` y el prompt `tú> ` vuelve a mostrarse

#### Scenario: Segundo Ctrl+C
- **GIVEN** una tarea ya cancelada por `Ctrl+C` que aún no ha terminado
- **WHEN** llega otro `Ctrl+C`
- **THEN** el proceso termina con código `0` en menos de 2 s aunque haya una lectura de `stdin` pendiente

### Requirement: Persistencia de turnos
Cada turno SHALL guardar el mensaje del usuario (`role = user`) y la respuesta (`role = assistant`, con el modo efectivo) en el historial, y cada tarea delegada SHALL registrarse con su estado, tokens y coste.

#### Scenario: Turno guardado
- **WHEN** el usuario envía `hola` y el `front` responde `Hola, señor.` en modo `text`
- **THEN** la conversación contiene un mensaje `user` con `hola` y un mensaje `assistant` con `Hola, señor.` y `reply_mode = text`

### Requirement: Ayuda en español
`tony chat --help` SHALL describir el comando y las opciones `--config`, `--agents-dir` y `--new` en español, y `tony --help` SHALL listar `chat` junto a `run` y `version`.

#### Scenario: Ayuda de chat
- **WHEN** se ejecuta `tony chat --help`
- **THEN** la salida describe `--config`, `--agents-dir` y `--new` en español
