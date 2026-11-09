# Design

## Context

- `McpServer` (`tony/core/loader/tool_json.py`) is `extra="forbid"`; stdio-only keys are the `_STDIO_ONLY` set (`args`, `env`) and a stdio entry carrying an HTTP key is rejected in `_one_transport`. `isolation` fits this mechanism.
- `McpManager._connect` dumps the declared server with `exclude_unset=True`, resolves placeholders, re-validates into `McpServer`, then `_transport` builds `StdioServerParameters(command=stdio_command(...), args, env=server.env or None)`.
- The MCP SDK (`mcp/client/stdio.py`) spawns with `get_default_environment() | (server.env or {})`. The default set on POSIX is `HOME, LOGNAME, PATH, SHELL, TERM, USER` copied from the host. The SDK can only add keys, never remove them: passing a restricted `env` still leaks `LOGNAME`, `SHELL`, `TERM`, `USER`, and omits `LANG`/`LC_ALL`.
- `tony/core/diagnostics/checks.py` (present in the working tree, from the unarchived doctor change) exposes `run_checks(root, which, find_spec, environ)`, producing `Check(name, status, hint)` rows; `warn` does not affect `exit_code`.
- `tests/fakes/fake_fs_server.py` already has an `echo_env(name)` tool returning `os.environ.get(name, "")`; the smoke test reuses it, so no new fake server is needed. A tiny dedicated script is still acceptable if a full dump is preferred (see Decision 4).
- The working tree holds four uncommitted changes touching `manager.py`, `tool_json.py` area files, and `tests/core/mcp`; implementation must be applied on top of the current files, not on `main`.

## Goals / Non-Goals

**Goals:**
- Opt-in per-server environment allowlist; a non-allowed host variable is truly absent from the child.
- No behavior change without `isolation`.
- Doctor warning for allowlisted variables missing from the host.

**Non-Goals:**
- OS sandboxing, filesystem roots, Flatpak permissions, HTTP servers, network restrictions.
- A `tony mcp add` flag (the writer already validates arbitrary entries; users edit `tool.json`).
- Reading allowlisted values from `config/.env` (host environment only).

## Decisions

1. **Schema.** `class Isolation(BaseModel, extra="forbid"): env_allow: list[EnvName] = []`, where `EnvName` matches `[A-Za-z_][A-Za-z0-9_]*`. `McpServer.isolation: Isolation | None = None`; add `"isolation"` to `_STDIO_ONLY`. `tool_json_writer.add_server` needs no change (it validates through `parse_tool_spec`); a test pins that. Presence of the object (even `{}`) means isolated.

2. **Environment composition** (pure function `isolated_environment(server, host) -> dict[str, str]` in a new `tony/core/mcp/isolation.py`):
   - start empty; copy host values for `PATH, HOME, LANG, LC_ALL` (fixed base) and for each `env_allow` name, only when set in `host`;
   - then apply `server.env` (already placeholder-resolved), which overrides host values;
   - nothing else. Host = `os.environ` read at spawn time via an optional `McpManager(host_environ=None)` argument (None means `os.environ`), keeping the four existing call sites unchanged.

3. **Bypassing the SDK merge.** Chosen: a stdlib-only launcher script `tony/core/mcp/isolated_exec.py`. For isolated servers `_transport` builds `StdioServerParameters(command=sys.executable, args=["-I", <launcher path>, stdio_command(command), *args], env={"TONY_ISOLATED_ENV": json.dumps(isolated_environment(...))})`. The SDK adds its defaults to the launcher process only. The launcher pops `TONY_ISOLATED_ENV`, parses it, and calls `os.execvpe(command, [command, *args], env)`, replacing itself, so the connector sees exactly the composed environment (PATH lookup uses the composed `PATH`). Stdin/stdout stay the MCP pipes; stderr stays the masked log.
   - The values travel in the launcher's environment, not argv, so they do not show in `ps` output.
   - Alternatives rejected: (a) monkeypatching `mcp.client.stdio.get_default_environment` is process-global, racy with concurrent connects of non-isolated servers, and breaks on SDK refactors; (b) `env -i K=V cmd` puts secrets in argv; (c) reimplementing `stdio_client` duplicates process-group and shutdown handling; (d) passing a restricted `env` only leaves `LOGNAME/SHELL/TERM/USER` present, failing the "truly absent" rule.
   - POSIX only (Linux/Flatpak target); on Windows `execvpe` does not replace the process, so isolation is documented as POSIX-only.

4. **Smoke test.** Spawn a real `McpManager` with an isolated entry for the existing fake filesystem server (`fake_fs_entry`) and `isolation={"env_allow": ["ALLOWED_VAR"]}`, host environ injected as `{"ALLOWED_VAR": "a", "SECRET_VAR": "s", "USER": "u", "PATH": os.environ["PATH"], "HOME": ...}`. Call `fs.echo_env` for each name: `ALLOWED_VAR` returns `a`; `SECRET_VAR`, `USER`, `SHELL`, `TERM`, `LOGNAME` return empty; a declared `env` value is returned. A negative control without `isolation` shows the SDK default (`USER`) is present. Local subprocess only, no network, well under 10 s. Because the launcher's SDK-side environment is the real `os.environ`, the test sets `SECRET_VAR` through `monkeypatch.setenv` only to prove the launcher drops it; the injected `host_environ` drives composition.

5. **Doctor.** New row per isolated server with a non-empty allowlist: name `isolation:<agent>/<server>`, `warn` with hint `env_allow variables not set in the host: A, B` (sorted) when any is missing; no row otherwise. Uses the `environ` already passed to `run_checks`; it does not use `.env` file values (runtime reads only the host). Non-executing like the other checks.

6. **Logging/masking.** Unchanged; isolated environment values coming from declared `env` placeholders are already registered with the masker in `_connect`.

## Risks / Trade-offs

- Extra interpreter hop (~tens of ms) per isolated connect; acceptable under the 30 s connect timeout and opt-in only.
- A server that needs variables beyond the base set (`XDG_*`, `TMPDIR`, `NODE_*`) fails until the operator allowlists them; documented in the doctor hint and tool.json docs.
- `-I` also ignores `PYTHON*` variables for the launcher only; the connector is unaffected because it is exec'd with the composed environment.
- If the SDK later stops merging defaults, the launcher still works (idempotent).
- Launcher failure (command not found) surfaces as the server exiting early; the manager already marks it down with a reason, and the launcher writes a one-line message to stderr (the masked log) before exiting 127.
