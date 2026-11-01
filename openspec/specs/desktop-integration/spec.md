# desktop-integration Specification

## Purpose
Defines how the desktop app integrates with the Linux desktop: the tray icon and its state, a single running instance that `tony --focus` and a global hotkey can raise with the microphone on, and native notifications for confirmations pending while the window is out of sight.

## Requirements

### Requirement: Tray icon
When `desktop.tray` is `true` and the desktop offers a system tray, the app SHALL show a tray icon with the actions «Mostrar/Ocultar» (toggles the window) and «Salir» (quits like closing the window). Without a system tray, or with `desktop.tray: false`, no tray icon SHALL be created and the app SHALL work normally.

#### Scenario: Hide and show from the tray
- **WHEN** the window is visible and the user picks «Mostrar/Ocultar» twice
- **THEN** the window is hidden and then shown again, and the core keeps running meanwhile

#### Scenario: Tray disabled
- **WHEN** `config/tony.yaml` sets `desktop.tray: false`
- **THEN** no tray icon is created

### Requirement: Tray state
The tray SHALL show one state: `idle` at start and after a turn's `result` or a front-agent `error`; `working` after `turn_started` or `task_started`, and after the pending confirmation is answered; `awaiting_confirmation` after `needs_confirmation`. The tooltip SHALL be `Tony — en espera`, `Tony — trabajando` or `Tony — esperando confirmación`, and the icon colour grey, `#2F6FED` or `#E0A100`.

#### Scenario: Turn with a confirmation
- **WHEN** the events `turn_started`, `task_started`, `needs_confirmation`, `tool_call` (same task), task `result` and turn `result` arrive in order
- **THEN** the state goes `working`, `working`, `awaiting_confirmation`, `working`, `working`, `idle`

#### Scenario: Tooltip
- **WHEN** the state is `awaiting_confirmation`
- **THEN** the tooltip is `Tony — esperando confirmación` and the icon is `#E0A100`

### Requirement: Single instance
Only one desktop app SHALL run per user. A new `tony` (no subcommand) SHALL ask the running instance to show and raise its window and exit 0. The channel SHALL be a local socket accessible only to the user and SHALL accept only the messages `show` and `focus`; any other message SHALL be ignored.

#### Scenario: Second launch
- **WHEN** the app is running hidden and the user runs `tony`
- **THEN** the running window is shown and raised, and the second process exits 0 without opening a window

#### Scenario: Unknown message
- **WHEN** a local client sends `record` to the running instance
- **THEN** nothing happens and the instance keeps running

#### Scenario: Stale socket
- **WHEN** a previous instance crashed leaving its socket behind and the user runs `tony`
- **THEN** the new process starts the app and serves the channel

### Requirement: Focus command
`tony --focus` SHALL send `focus` to the running instance, which shows, raises and focuses its window and starts listening; with no running instance it SHALL launch the app and start listening once voice is `ready`. With voice `unavailable`, an `error` event naming the reason SHALL be shown instead.

#### Scenario: Focus a running instance
- **WHEN** the app is minimised and the user runs `tony --focus`
- **THEN** the window is restored and focused, the microphone starts listening and the command exits 0

#### Scenario: Focus with no instance
- **WHEN** no instance runs and the user runs `tony --focus`
- **THEN** the app opens and starts listening when voice becomes `ready`

### Requirement: Global hotkey on X11
When `XDG_SESSION_TYPE` is `x11`, the app SHALL register `desktop.hotkey` (default `Super+J`) as a global hotkey that acts like `tony --focus`. On any other session type no hotkey SHALL be registered. An invalid hotkey SHALL publish an `error` naming `desktop.hotkey` and the app SHALL keep working.

#### Scenario: X11 session
- **WHEN** the app starts with `XDG_SESSION_TYPE=x11` and the user presses Super+J
- **THEN** the window is raised and listening starts

#### Scenario: Wayland session
- **WHEN** the app starts with `XDG_SESSION_TYPE=wayland`
- **THEN** no global hotkey is registered

#### Scenario: Hotkey syntax
- **WHEN** `desktop.hotkey` is `Ctrl+Alt+Space`, `Super+F2` or `Super+`
- **THEN** the first two are accepted and `Super+` is rejected naming `desktop.hotkey`

### Requirement: Confirmation notification
When a `needs_confirmation` event arrives while the window is hidden or minimised, the app SHALL show one native notification titled `Tony — Edith` with the (masked) question. Clicking it SHALL show, restore and raise the window with the Edith zone expanded and keyboard focus on «Denegar». No notification SHALL be shown while the window is visible and not minimised.

#### Scenario: Hidden window
- **WHEN** the window is hidden in the tray and a confirmation for `filesystem.delete_file` becomes pending
- **THEN** one notification `Tony — Edith` with the question is shown

#### Scenario: Notification clicked
- **WHEN** the user clicks that notification
- **THEN** the window is shown on the Edith banner with focus on «Denegar»

#### Scenario: Visible window
- **WHEN** a confirmation becomes pending while the window is visible
- **THEN** no notification is shown

#### Scenario: Notifications unavailable
- **WHEN** no notification service is reachable
- **THEN** an `error` event with source `notifications` is shown once and the banner still works
