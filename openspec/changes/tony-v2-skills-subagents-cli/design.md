# Design

## Context

- MCP connections are opened per task (`McpManager` inside `run_task`) and per front-agent turn (`agent_tools`); none outlive them. Each task re-reads `agent.md`, `tool.json` and `policy.yaml` from disk and fails on an invalid file.
- The engine receives a fixed tool list per SDK client session (`create_sdk_mcp_server` per server at session start).
- `NativeTool.run(args)` is context-free and the production registry `NATIVE_TOOLS` is empty; `RunDeps.native` serves both for name validation (`keys()`) and execution.
- `EdithGuard` holds one `Policy` for the task; `TaskSupervisor` holds the task's `Limits`.
- The Activity presenter already nests `tool_call` events whose `agent` is `<agent>/<sub>` under the task named by `task_id`; the shipped policy already allows `tony.read_skill` and `tony.run_subagent`.
- Serving `stdio_client` contexts are anyio task-group bound: they must be closed by the task that opened them.

## Goals / Non-Goals

**Goals:**
- Natives that know the calling agent, with no change to `McpManager`'s calling contract.
- One guard, one supervisor, one task log per task, subagents included.
- Hot reload that never swaps a valid configuration for an invalid one and never touches a running task's connections.

**Non-Goals:**
- Restarting servers inside a running task or re-registering tools in a live SDK session.
- Watching `agent.md`, `SKILL.md` or `config/tony.yaml` (skills and subagents are read per task anyway).
- Subagents of subagents; parallel subagent runs; per-subagent timeouts.
- Hot reload in `tony run` (one task per process, already reads files fresh).

## Decisions

### D1. Reload model: snapshot per task, re-probe changed servers
A valid `tool.json` change replaces the agent's declaration for the next task/turn; Tony only connects-lists-closes the added/changed servers to refresh their `mcp_status`, and publishes `up: false, reason "removed from tool.json"` for removed ones (no new event type).
- Alternative: diff-restart servers inside live `McpManager`s. Rejected: the SDK session's tool list is fixed at start, closing a stdio server from the watcher task breaks anyio cancel-scope affinity (the deadlock class previous phases fought), and the model would see tools vanish mid-plan.
- Trade-off: a task running for minutes does not see a server added meanwhile. Accepted; documented.

### D2. Live configuration sources (`tony/core/config/reload.py`)
- `PolicySource` protocol `current() -> Policy`; `StaticPolicy` (tony run) and `LivePolicy` (last valid, `reload() -> DefinitionError | None`).
- `ToolSpecSource` protocol `spec_for(agent_key) -> ToolSpec`; `LiveToolSpecs` caches last valid per key and falls back to reading the file when no valid entry exists.
- `RunDeps` gains `policy_source: PolicySource | None` and `tool_specs: ToolSpecSource | None`; `None` keeps today's read-from-disk behaviour, so `tony run` and existing tests are unchanged.
- `EdithGuard` takes a `PolicySource` and calls `current()` once per `decide` (verdict, allow-always offer, `confirm_timeout_s`). `TaskSupervisor` keeps a per-task `Limits` snapshot; `auth` stays per session (spec: config-reload "Policy applies to the next tool call").
- `load_agent` gains an optional `tools: ToolSpec` override so a live spec is used without re-reading an invalid file.

### D3. Watcher adapter isolated from reload logic
- `tony/core/config/watcher.py`: the only module importing `watchfiles`; `watch_config(root, guard, stop) -> AsyncIterator[set[Path]]` over `awatch(root / "agents", watch_filter=…, stop_event=stop)`, filter = file name `tool.json` (under `tool/`) or the guard's `policy.yaml`; batches de-duplicated.
- `ConfigReloader(root, guard, live_policy, live_tools, publish, stderr, probe)` consumes any `AsyncIterator[set[Path]]`; tests drive it with a fake stream; one integration test uses real `watchfiles` with `debounce=50`, `step=10`, bounded by `asyncio.timeout(5)`.
- Every path in a batch is re-read regardless of change kind (atomic `os.replace` saves surface as delete+add).
- Reloads are handled one batch at a time; re-probes run as background tasks owned by the reloader and cancelled on stop.
- Errors: `core_events.error("reload", "<file>: <error>")` and `tony: warning: <file>: <error>` on stderr.

### D4. Native tools as per-run factories
- `tony/core/mcp/native.py`: `NativeScope` (root, agent key, agent folder, `run_subagent` callback) and `NATIVE_TOOLS: dict[str, NativeFactory]` with exactly `read_skill`, `run_subagent`; `NativeFactory = Callable[[NativeScope], NativeTool]`.
- `RunDeps.native` becomes `Mapping[str, NativeFactory]`; validation still uses `keys()`; the runner binds `{name: factory(scope) for name in spec.native}` and passes bound tools to the unchanged `McpManager(native=…)`.
- Implementations live in `tony/core/orchestrator/natives.py` (orchestrator layer, because `run_subagent` needs the runner); `tony/core/mcp` keeps no dependency on orchestration.
- Alternative: pass context through `run(args, context)`. Rejected: changes `McpManager.call` and every native test for no gain.

### D5. Skills and subagents loaders (`tony/core/loader/skills.py`, `subagents.py`)
- Agent key `<agent>` or `<agent>/<sub>` maps to `agents/<agent>/` or `agents/<agent>/subagents/<sub>/`; `load_agent` is generalised to a folder + key, keeping current error texts.
- `list_skills(folder) -> (skills, errors)` enumerates `skills/*/SKILL.md`, reuses `split_frontmatter`, strict `{name, description}` model.
- Lookup by name only matches enumerated folder names; input is never joined into a path (path traversal is impossible by construction).
- `load_subagent(root, parent, name, config)` = generalised `load_agent` + `role == worker`, `description` required, `run_subagent` not in `native` (error field `native` on the subagent's `tool.json`).
- Prompt sections (`tony/core/orchestrator/prompt_sections.py`): `with_sections(body, skills, subagents)` appends `## Skills` / `## Subagentes`, sorted; used by the runner (worker and subagent) and by `Conversation._system_prompt` (front), only for declared natives.
- Invalid skills: `error` event source `skills` into the task log and publisher; never fatal.

### D6. Subagent execution inside the parent task (runner)
- `run_subagent` native → `runner._run_subagent(parent_run, name, request)`: builds a child `_TaskRun` sharing `id`, `log`, `guard`, `supervisor`, `publish`, `masker`, `variables`, `policy`; own `AgentDefinition`, `model_id`, agent name `<agent>/<sub>`; runs `deps.engine.run` inside its own `_proxied_tools` (own `McpManager`, closed on return).
- Logs `subagent_started` / `subagent_finished`; usage → parent log `token_usage`, supervisor, and a per-task usage accumulator summed into the task `result` event.
- Engine exception → result `errores` + outcome `error`, returned (not raised). `CancelledError` propagates (parent cancel/timeout unwinds the child's `McpManager`).
- No `task_started`/`result` core events for the child: the Activity presenter needs no change.
- Alternative: run the subagent as a separate task with its own id and supervisor. Rejected: breaks "children of the parent task", lets a subagent escape the parent's limits, doubles audit correlation work.

### D7. Proxy changes
- `ToolProxy` passes `agent` to `log_events.tool_call/tool_result` (golden `tests/golden/task_log.jsonl` updated).
- `UNTIMED_TOOLS = frozenset({"tony.run_subagent"})` skip `asyncio.wait_for`; the parent's `_race` bounds it.

### D8. `tony mcp add` writer (`tony/core/loader/tool_json_writer.py`)
- `add_server(root, agent_key, name, entry, *, native_tools, lock_timeout=5.0)`.
- Lock: `fcntl.flock(LOCK_EX | LOCK_NB)` on `tool.json.lock` polled every 50 ms; kernel releases it on process death (no stale locks). Linux-only is acceptable (single-user Bazzite target).
- Under the lock: read, `json.loads` (dict order kept), duplicate check, insert, validate with `parse_tool_spec`, write `tool.json.tmp` in the same folder, `fsync`, `os.replace`.
- The watcher ignores both `tool.json.lock` and `tool.json.tmp`.
- Secret warning uses the existing `SECRET_NAME` regex from `tony/core/config/secrets.py`; values are never printed.
- Typer sub-app `mcp` in `tony/apps/cli/main.py`; `--arg`/`--header`/`--env` are repeatable options; `K=V` split on the first `=`.

### D9. `tony mcp list`
- Sequential `McpManager` per agent key with a discarding sink, real variables and masker, existing 10 s per-server timeout; tool counts grouped by `CatalogTool.server`; natives not listed.
- Agent discovery: sorted `agents/*/tool/tool.json` and `agents/*/subagents/*/tool/tool.json`.

### D10. Hosts
- `CoreRuntime._start` creates `LivePolicy` (seeded with the start policy), `LiveToolSpecs` (seeded silently from every discoverable `tool.json`), passes them via `RunDeps`, and starts the reloader as a background task stopped in `_shutdown`. `run_chat` does the same around the chat loop.
- `Conversation` asks `deps.tool_specs` for the front agent's spec each turn.

### D11. Mutation-testing groups
Pure logic is kept out of modules exercised by MCP integration tests so most groups avoid them: loaders, writer, reload decisions, prompt sections and natives each have dedicated fast tests; `runner` and `runtime` remain heavy and get their own groups. `tony/core/config/watcher.py` (thin `watchfiles` glue covered by one real-filesystem test) is added to `do_not_mutate` with that justification.

## Risks / Trade-offs

- [Running task misses a newly added server] → Documented; next task/turn sees it; `mcp_status` updates immediately.
- [Policy swapped mid-task changes a pending decision] → `current()` is read once per `decide`, so one verdict never mixes two policies.
- [watchfiles debounce delays a reload ~1.6 s by default] → Acceptable for interactive edits; tests use a short debounce.
- [Editor writes partial file then completes it] → Partial content fails validation, previous config stays, the next event applies the complete file.
- [Subagent recursion / runaway cost] → Depth fixed at 1 by loader rule; subagent steps counted per agent key; shared task timeout and token alert.
- [Literal secrets written by `tony mcp add` into a committed `tool.json`] → Stderr warning recommending `${VAR}`; values never echoed. Not refused, to keep non-secret keys like `PIN_MODE=1` usable.
- [Server-name rule rejects an existing hand-written `tool.json`] → Bundled files comply; the error names the file and field.
- [flock on network filesystems] → Out of scope (local single-user target).

## Migration Plan

- Additive except: `tool_call`/`tool_result` task-log lines gain `agent` (consumers read JSON objects; golden updated), and server names with `.`/`__` are now rejected.
- `watchfiles` added with `uv add watchfiles`; `uv.lock` committed.
- Rollback: revert the change; no persisted data format changes besides `tool.json` entries written by `tony mcp add`, which remain valid input for the previous version.
