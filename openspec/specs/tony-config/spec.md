# tony-config Specification

## Purpose
Defines Tony's global configuration in `config/tony.yaml`, its defaults and model aliases, and how secrets from `config/.env` are kept out of everything except MCP server processes and connections.

## Requirements

### Requirement: Configuration schema and defaults
`config/tony.yaml` SHALL accept `front`, `worker`, `guard` (agent folder names), `reply_mode` (`auto|voice|text|both`), `models` (alias to model id), `voice` (`stt`, `vad`, `tts_default`) and `desktop` (`hotkey`, `tray`, `theme`). Missing keys or a missing file SHALL take the defaults; unknown keys MUST be rejected.

#### Scenario: Missing file uses defaults
- **WHEN** `config/tony.yaml` does not exist
- **THEN** the configuration is `front: jarvis`, `worker: viernes`, `guard: edith`, `reply_mode: auto`, `models: {claude-haiku: claude-haiku-5-5, claude-sonnet: claude-sonnet-5-5}`, `voice: {stt: faster-whisper/small, vad: silero, tts_default: kokoro/em_alex}`, `desktop: {hotkey: "Super+J", tray: true, theme: system}`

#### Scenario: Partial file merges with defaults
- **WHEN** `config/tony.yaml` contains only `reply_mode: text`
- **THEN** `reply_mode` is `text` and every other key has its default value

#### Scenario: Invalid reply mode
- **WHEN** `reply_mode` is `loud`
- **THEN** loading fails with an error naming `config/tony.yaml` and the field `reply_mode`

#### Scenario: Unknown key
- **WHEN** `config/tony.yaml` contains `engine: litellm`
- **THEN** loading fails with an error naming `config/tony.yaml` and the field `engine`

### Requirement: Model alias resolution
Agents SHALL reference models only by alias; the alias SHALL be resolved to a model id through `models` when the agent runs.

#### Scenario: Default alias resolves
- **WHEN** an agent with `model: claude-sonnet` runs with default configuration
- **THEN** the model id used is `claude-sonnet-5-5`

### Requirement: Secrets source
Secret values SHALL be read only from `config/.env` (and the process environment). `config/.env` MUST NOT be required to exist for offline runs.

#### Scenario: Missing env file
- **WHEN** `config/.env` does not exist and no placeholder needs a missing variable
- **THEN** configuration loads without error

### Requirement: Placeholder resolution at MCP start
`${VAR}` placeholders in `tool.json` `command`, `args`, `env`, `url` and `headers` SHALL be resolved only when the MCP server is started. A placeholder whose variable is undefined SHALL make only that server fail to start, with an error naming the server and the variable but not any value.

#### Scenario: Placeholder resolved for the server only
- **WHEN** `tool.json` declares `"env": {"TOKEN": "${GITHUB_TOKEN}"}` and `config/.env` defines `GITHUB_TOKEN=s3cr3t`
- **THEN** the server process receives `TOKEN=s3cr3t` and the loaded agent definition still contains `${GITHUB_TOKEN}`

#### Scenario: Undefined variable
- **WHEN** a server references `${MISSING_VAR}` and the variable is not defined
- **THEN** that server is reported as failed with a message naming `MISSING_VAR` and the other servers still start

### Requirement: Secrets never leak
No agent prompt, tool result returned to an agent, task log line or CLI output SHALL contain a resolved secret value; any occurrence of a value resolved from a placeholder MUST be replaced by `***` before it leaves the core.

#### Scenario: Tool echoes a secret
- **WHEN** a tool result contains the resolved value `s3cr3t` of a placeholder used by that agent's servers
- **THEN** the result passed to the agent and the `tool_result` log event contain `***` instead of `s3cr3t`
