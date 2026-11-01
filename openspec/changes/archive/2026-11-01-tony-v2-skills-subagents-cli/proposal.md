# Proposal

## Why

Tony v2 can converse (Jarvis), execute tasks (Viernes) and guard every tool call (Edith), but extending it still needs code or a restart: there are no reusable instructions (skills), no way to hand a sub-problem to a specialised worker, adding an MCP server means hand-editing JSON, and edits to `tool.json` or `policy.yaml` are only seen by a fresh process. This change makes Tony extensible from files and the CLI alone, while keeping Edith as the single gate for every call.

## What Changes

- **Skills**: `agents/<agent>/skills/<name>/SKILL.md` with frontmatter `name` and `description` and a non-empty Markdown body. An agent that declares the native `read_skill` gets a `## Skills` section in its system prompt listing only `name: description`; the native tool `tony.read_skill(name)` returns the body. An unknown name returns an error result listing the available skills. A new skill folder is picked up by the next task with no code change.
- **Subagents**: `agents/<agent>/subagents/<name>/` with the same structure as an agent (`agent.md` with role `worker` plus a required `description`, `tool/tool.json`, optional `skills/`). An agent that declares the native `run_subagent` gets a `## Subagentes` prompt section; `tony.run_subagent(name, tarea)` runs the subagent with its own MCP servers inside the parent task and returns its structured `{resumen, datos, pasos, errores}`. Every subagent tool call is judged by Edith and audited with `agent: "<agent>/<name>"`; its events go to the parent task's log and appear as children of the parent task in the Activity zone. Subagents cannot run subagents (depth 1).
- **Native tool registry**: Tony now ships two natives, `tony.read_skill` and `tony.run_subagent`, bound per agent run. The bundled Viernes declares both (the shipped policy already allows them).
- **`tony.run_subagent` is exempt from the per-call tool timeout**; it is bounded by the parent task's timeout and cancellation instead.
- **`tony mcp add <name> <command-or-url> [--arg A]... [--header K=V]... [--env K=V]... --agent <agent>`** writes a stdio entry (or an HTTP entry when the target starts with `http://` or `https://`) into the agent's `tool.json`, refuses duplicates and invalid names, validates the result with the same loader rules, and serialises writers with an exclusive lock on `tool.json.lock` plus an atomic replace.
- **`tony mcp list [--agent <agent>]`** connects every declared server and prints `agent server state tools`, exiting 0 even when a server is down.
- **Hot reload with `watchfiles`** in the long-lived hosts (desktop core runtime and `tony chat`): a `tool.json` change re-probes only the added/changed/removed servers and the next task or turn uses the new catalog; a `policy.yaml` change applies to the next tool call, including calls of a task already running. Invalid YAML/JSON or a schema error keeps the previous valid configuration and emits an `error` event plus a stderr warning naming the file and the error.
- MCP server names in `tool.json` are restricted to letters, digits and single `-`/`_` separators (no `.`, no `__`), so tool ids and engine tool names always round-trip.
- Task log `tool_call`/`tool_result` events gain an `agent` field; new `subagent_started`/`subagent_finished` events bracket a subagent run.
- New runtime dependency: `watchfiles`.

## Capabilities

### New Capabilities
- `agent-skills`: skill folder format, prompt listing and the `tony.read_skill` native tool.
- `subagents`: subagent folder format, prompt listing, the `tony.run_subagent` native tool, guard/audit identity, events and limits.
- `mcp-cli`: the `tony mcp add` and `tony mcp list` commands and the locked, validated `tool.json` write.
- `config-reload`: file watching of `tool.json` and `policy.yaml`, selective server re-probe, live policy and keep-last-valid on errors.

### Modified Capabilities
- `agent-definitions`: optional `description` frontmatter field; server name pattern in the tool declaration schema; bundled Viernes declares `read_skill` and `run_subagent`.
- `mcp-connections`: the production native tool registry provides exactly `read_skill` and `run_subagent`.
- `tool-proxy`: `tony.run_subagent` exempt from the per-call tool timeout.
- `task-log`: `agent` on `tool_call`/`tool_result`; `subagent_started`/`subagent_finished` events.
- `guard-audit`: subagent scenario for the `agent` field.

## Impact

- Code: `tony/core/loader` (new `skills.py` and `subagents.py`, server-name rule, frontmatter `description`), `tony/core/mcp/native.py` (bound native factories), new `tony/core/orchestrator/natives.py` (`read_skill`, `run_subagent`), `tony/core/orchestrator/runner.py` (natives binding, subagent run, prompt sections, policy/tool-spec sources), `tony/core/orchestrator/proxy.py` (timeout exemption, log `agent`), `tony/core/guard/edith.py` (live policy source), new `tony/core/config/reload.py` and `tony/core/config/watcher.py`, new `tony/core/loader/tool_json_writer.py`, `tony/apps/cli/main.py` (`mcp` sub-app, chat wiring), `tony/core/orchestrator/runtime.py` (reloader wiring).
- Data: `agents/viernes/tool/tool.json` declares `"native": ["read_skill", "run_subagent"]`; `tests/golden/task_log.jsonl` updated for the `agent` field.
- Dependencies: `watchfiles` added to `pyproject.toml`.
- No change to the desktop widgets or presenters: the Activity zone already nests `<agent>/<subagent>` calls.
