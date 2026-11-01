# flatpak-packaging Specification

## Purpose
Defines the Flatpak packaging shipped in `packaging/`: the manifest for `io.github.renzoramosdev.Tony`, its sandbox permissions, desktop entry and icon, and the documentation for building it locally.

## Requirements

### Requirement: Flatpak manifest
`packaging/io.github.renzoramosdev.Tony.yml` SHALL be a valid Flatpak manifest with app id `io.github.renzoramosdev.Tony`, command `tony`, a Python 3.12 runtime, a PortAudio module, the Node.js SDK extension, and Tony installed with its `voice` and `desktop` extras from hash-pinned requirements after building the desktop web front with `npm ci` and `npm run build`.

#### Scenario: Manifest parses
- **WHEN** the manifest is loaded as YAML
- **THEN** it has `id: io.github.renzoramosdev.Tony`, `command: tony`, a module installing Tony and a PortAudio module whose source has a `sha256`

#### Scenario: Pinned Python dependencies
- **WHEN** the Tony module's build commands are read
- **THEN** they install the requirements file shipped in `packaging/` with `--require-hashes`

#### Scenario: Web front built in the sandbox build
- **WHEN** the manifest is read
- **THEN** `sdk-extensions` contains a `org.freedesktop.Sdk.Extension.node` extension and the Tony module runs `npm --prefix tony/apps/desktop/web ci` and `npm --prefix tony/apps/desktop/web run build` before installing Tony

### Requirement: Sandbox permissions
The manifest's `finish-args` SHALL be exactly `--socket=wayland`, `--socket=fallback-x11`, `--socket=pulseaudio`, `--share=network`, `--filesystem=home`, `--talk-name=org.freedesktop.Notifications`, `--device=dri` and `--env=QTWEBENGINE_DISABLE_SANDBOX=1`.

#### Scenario: Exact finish-args
- **WHEN** the manifest's `finish-args` are read
- **THEN** they equal that set, with no other permission

### Requirement: Desktop entry and icon
`packaging/` SHALL contain `io.github.renzoramosdev.Tony.desktop` (`Type=Application`, `Name=Tony`, `Exec=tony`, `Icon=io.github.renzoramosdev.Tony`, a desktop action running `tony --focus`) and a scalable icon with the same id, both installed by the manifest.

#### Scenario: Desktop file content
- **WHEN** the `.desktop` file is parsed
- **THEN** its `Desktop Entry` group has `Exec=tony` and `Icon=io.github.renzoramosdev.Tony`, and one action's `Exec` is `tony --focus`

### Requirement: Packaging documentation
The README SHALL document building and installing the Flatpak locally, binding a desktop custom shortcut to `tony --focus` (or its `flatpak run` form) on Wayland, and that MCP servers launched with `npx` need Node available inside the sandbox, recommending `uvx` servers. It SHALL also state that the build compiles the web front and why the sandbox has GPU access and the web engine sandbox switch. Building the Flatpak SHALL NOT be part of the automated tests.

#### Scenario: README sections
- **WHEN** the README is read
- **THEN** it contains the `flatpak-builder` command, `tony --focus` for Wayland shortcuts and a note recommending `uvx` over `npx`

#### Scenario: README sandbox notes
- **WHEN** the README's Flatpak section is read
- **THEN** it mentions `--device=dri` and `QTWEBENGINE_DISABLE_SANDBOX`
