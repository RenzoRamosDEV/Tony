# Spec Delta

## Purpose

Defines the Flatpak packaging shipped in `packaging/`: the manifest for `io.github.renzoramosdev.Tony`, its sandbox permissions, desktop entry and icon, and the documentation for building it locally.

## ADDED Requirements

### Requirement: Flatpak manifest
`packaging/io.github.renzoramosdev.Tony.yml` SHALL be a valid Flatpak manifest with app id `io.github.renzoramosdev.Tony`, command `tony`, a Python 3.12 runtime, a PortAudio module, and Tony installed with its `voice` and `desktop` extras from hash-pinned requirements.

#### Scenario: Manifest parses
- **WHEN** the manifest is loaded as YAML
- **THEN** it has `id: io.github.renzoramosdev.Tony`, `command: tony`, a module installing Tony and a PortAudio module whose source has a `sha256`

#### Scenario: Pinned Python dependencies
- **WHEN** the Tony module's build commands are read
- **THEN** they install the requirements file shipped in `packaging/` with `--require-hashes`

### Requirement: Sandbox permissions
The manifest's `finish-args` SHALL be exactly `--socket=wayland`, `--socket=fallback-x11`, `--socket=pulseaudio`, `--share=network`, `--filesystem=home` and `--talk-name=org.freedesktop.Notifications`.

#### Scenario: Exact finish-args
- **WHEN** the manifest's `finish-args` are read
- **THEN** they equal that set, with no other permission

### Requirement: Desktop entry and icon
`packaging/` SHALL contain `io.github.renzoramosdev.Tony.desktop` (`Type=Application`, `Name=Tony`, `Exec=tony`, `Icon=io.github.renzoramosdev.Tony`, a desktop action running `tony --focus`) and a scalable icon with the same id, both installed by the manifest.

#### Scenario: Desktop file content
- **WHEN** the `.desktop` file is parsed
- **THEN** its `Desktop Entry` group has `Exec=tony` and `Icon=io.github.renzoramosdev.Tony`, and one action's `Exec` is `tony --focus`

### Requirement: Packaging documentation
The README SHALL document building and installing the Flatpak locally, binding a desktop custom shortcut to `tony --focus` (or its `flatpak run` form) on Wayland, and that MCP servers launched with `npx` need Node available inside the sandbox, recommending `uvx` servers. Building the Flatpak SHALL NOT be part of the automated tests.

#### Scenario: README sections
- **WHEN** the README is read
- **THEN** it contains the `flatpak-builder` command, `tony --focus` for Wayland shortcuts and a note recommending `uvx` over `npx`
