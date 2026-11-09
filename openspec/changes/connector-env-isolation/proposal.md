# Proposal

## Why

A stdio MCP connector is a third-party process. Today it inherits a fixed set of host variables from the MCP SDK (`HOME`, `LOGNAME`, `PATH`, `SHELL`, `TERM`, `USER`) plus its declared `env`, and there is no way to say "this connector gets only these variables". Operators need an opt-in, per-server way to limit what a connector can see of the host environment.

## What Changes

- `tool.json` stdio server entries accept an optional `isolation` object `{env_allow: string[]}`.
- With `isolation`, the connector process environment is exactly: the `env_allow` variables present in the host environment, the server's declared `env`, and `PATH`, `HOME`, `LANG`, `LC_ALL` (host values). Every other host variable, including the SDK defaults `LOGNAME`, `SHELL`, `TERM`, `USER`, is absent.
- Without `isolation`, behavior is unchanged (additive, no migration).
- `tony doctor` reports a server whose `env_allow` names a variable missing from the host as `warn`.
- A smoke test starts a fake stdio server that echoes its environment and asserts a non-allowed variable is absent.
- Out of scope: operating-system sandboxing, filesystem roots, Flatpak permission changes, HTTP servers, a CLI flag on `tony mcp add`.
- Safety invariant: no permission, confirmation or PIN is granted or bypassed; tool calls still go through the guard.

## Capabilities

### New Capabilities
- `connector-isolation`: the isolated-environment rule for stdio connectors and the doctor warning for unset allowlisted variables.

### Modified Capabilities
- `agent-definitions`: the tool declaration schema accepts `isolation` on stdio entries only.
- `mcp-connections`: stdio launch builds the environment from the isolation rule when declared.

## Impact

- Code: `tony/core/loader/tool_json.py`, `tony/core/mcp/manager.py`, a new stdlib-only launcher module under `tony/core/mcp/`, `tony/core/diagnostics/checks.py`.
- Tests: loader, manager stdio, diagnostics, a new isolation smoke test with a tiny fake server.
- No new dependency, no network, no change to `policy.yaml`.
- Builds on the working tree that already contains the doctor (`tony/core/diagnostics/`), pending archive of `phase1-conversations-doctor-policy`.
