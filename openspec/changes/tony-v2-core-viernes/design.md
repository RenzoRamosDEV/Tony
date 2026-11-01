# Design

## Context

- Branch starts with only `.gitignore` (already covering every required ignore entry) and `openspec/config.yaml`. No main specs exist.
- v1 (branch `main`) is a reference only. Reusable ideas: strict pydantic models for `agent.md`/`tool.json`, the "execution barrier" proxy that wraps each catalog tool as an in-process SDK MCP tool, `mcp__<server>__<tool>` name mapping with a `can_use_tool` deny for anything else, and a stdio fake filesystem server built with `mcp.server.mcpserver.MCPServer`. Not ported: LiteLLM/engine selection, web UI, confirm lists in `tool.json`, skills/subagents, effort/max_steps fields.
- Requirements: see `specs/*/spec.md`. Motivation: see proposal.md.

## Goals / Non-Goals

**Goals:**
- Ports-and-adapters core where the agent loop, MCP transport and guard are swappable, so the default test suite is fully offline.
- One execution path for tool calls (proxy) that phase 02 can extend with a real guard without touching the engine or MCP manager.

**Non-Goals:**
- Confirmation UX, policy files, audit beyond the task log (phase 02).
- Subagents, skills, memory, voice, desktop, Jarvis.
- Shipping any native tool (registry exists, empty in production).
- Concurrency of tasks, reconnection or hot reload of MCP servers.

## Decisions

### D1. Module layout and dependency direction
```
tony/apps/cli ──> tony/core/orchestrator ──> ports (Guard, ModelEngine, ToolCaller, EventSink)
                         │                         ▲
                         ├─> core/loader, core/config (pure, pydantic)
                         ├─> core/mcp (adapter: mcp SDK)        implements ToolCaller
                         ├─> core/guard (AllowAllGuard)         implements Guard
                         ├─> core/logging (JSONL sink)          implements EventSink
                         └─> core/orchestrator/claude_engine    implements ModelEngine (claude-agent-sdk)
```
- `core/loader`, `core/config`: pure models + parsing, no I/O beyond reading files.
- `core/events`: JSON-serializable event/message models (`ToolCall`, `TaskRequest`, `TaskResult`, log events) shared by all modules.
- Empty packages `core/{voice,memory}`, `apps/desktop` are created with `__init__.py` only (layout contract).
- Alternative rejected: v1's split into `runner/`, `channels/`, `subagents/` — more surface than this phase needs.

### D2. Engine port, fake model client
- `ModelEngine.run(spec, request, tools: list[ProxiedTool], model_id) -> EngineOutcome(text|structured, usage list)`. `ProxiedTool` = `{id, description, input_schema, handler(args) -> ToolReply}`.
- `ClaudeEngine` adapter: wraps each `ProxiedTool` in `create_sdk_mcp_server` per server group, `tools=[]`, `disallowed_tools` = built-ins, `allowed_tools=["mcp__<srv>__*"]` only for this agent's proxy servers, `can_use_tool` denying any name that does not map to a proxied id, `setting_sources=[]`, `strict_mcp_config=True`, `output_format` JSON schema of `TaskResult`, `model` = resolved id. Emits `token_usage` from `ResultMessage.usage`.
- `FakeModelEngine` (tests): scripted list of steps (`call tool X with args` / `final answer`); it invokes the same `ProxiedTool.handler`s, so the proxy, guard, MCP manager and log are exercised for real.
- Rationale: SDK internals (subprocess CLI) cannot run offline; the port keeps the SDK adapter thin. The adapter itself is covered by unit tests on `build_options`/name mapping/result parsing, and end-to-end only by the `evals` test.

### D3. Tool proxy as the single barrier
- `ToolProxy.call(envelope) -> ToolReply`: emit `tool_call` -> `guard.decide(envelope)` -> on `allow`, `asyncio.wait_for(caller.call(tool, args), 20)` -> mask secrets -> emit `tool_result` -> reply. `deny`/`confirm` -> error reply, not executed (no confirmation channel until phase 02).
- `Guard` is a `Protocol` with `async decide(ToolCall) -> Decision` (`Literal["allow","confirm","deny"]`); async so phase 02 can do I/O.
- All failures become `ToolReply(is_error=True, text=...)`; nothing raises into the engine.

### D4. MCP manager
- `McpManager` is an async context manager per task: for each server, inside `asyncio.wait_for(..., 10)`, open `stdio_client`/`streamablehttp_client` + `ClientSession.initialize()` + `list_tools()` in an `AsyncExitStack`. Failures -> `ServerStatus(down, reason)`, `error` event, stderr line; continue.
- Placeholder resolution happens here, just before launching (`${VAR}` from settings env); resolved values are registered with a `SecretMasker` used by proxy and log sink.
- Stdio server stderr goes to `logs/mcp/<server>.log` to keep the CLI's stdout clean (JSON only).
- Alternative rejected: one long-lived manager shared across tasks — needed for desktop later, unnecessary for a one-shot CLI.

### D5. Config and secrets
- `TonyConfig` (pydantic, `extra="forbid"`, defaults per spec) loaded from `config/tony.yaml`; `Secrets` via `pydantic-settings` reading `config/.env` (absent file allowed). Root dir resolved from `TONY_HOME` env var, defaulting to the current working directory — needed for tests to point at temp dirs.
- Validation errors are re-raised as `DefinitionError(file, field, message)` built from pydantic `loc` joined with `.`.

### D6. tool.json forbidden keys
- Recursive scan of the raw JSON before model validation; first `allow`/`confirm` key found yields `DefinitionError(file, "<dotted path>", "permissions belong to agents/edith/policy.yaml")`.

### D7. Task runner and CLI
- `run_task(agent_name, request, deps) -> TaskResult`: load config + agent, check role `worker`, open log, `task_started`, open `McpManager`, build proxied tools, `asyncio.wait_for(engine.run(...), 300)`, map outcome to `TaskResult` (unstructured -> `errores=["respuesta no estructurada"]`), `task_finished`, close everything in `finally`.
- CLI with `typer`: `tony run <agent> <task>` prints `TaskResult.model_dump_json()`; exit 0 iff `errores == []`; definition errors to stderr, exit 2.

### D8. Test doubles
- `tests/fakes/fake_fs_server.py`: stdio MCP server (`mcp` SDK) rooted at argv dir with `list_directory`, `read_file`, plus `sleep` and `echo_env` tools to test timeouts and secret masking.
- `tests/fakes/fake_engine.py`: `FakeModelEngine` (D2). `tests/fakes/guards.py`: `RecordingGuard(decision)`. In-memory `ListEventSink`.
- Timeouts are constructor parameters (defaults 10/20/300 s) so tests use sub-second values and stay within the 30 s per-test limit.

### D9. Mutation testing
- `mutmut` configured with `source_paths` limited to files changed by this change; `do_not_mutate` for the SDK adapter and stdio/HTTP transport code that cannot run in mutmut's copied tree, with justification recorded in the task. Run wrapped in `timeout 180`.

## Risks / Trade-offs

- [Claude Agent SDK API drift (options names, structured output)] -> pin the version in `pyproject.toml`; adapter is isolated and covered by the `evals` test.
- [Fake engine diverges from real SDK behavior] -> fake drives the same proxied handlers; `evals` test runs the identical scenario with the real model.
- [Stdio subprocess leaks on timeout] -> `AsyncExitStack` closed in `finally`; test asserts process exit.
- [Secret masking by value can miss transformed secrets (e.g. base64)] -> accepted for single-user local use; documented limitation.
- [`confirm` decisions silently fail in this phase] -> only reachable with a non-default guard; phase 02 adds the confirmation channel.
- [HTTP transport tested only via a local in-process server] -> acceptable; no real HTTP MCP is required in this phase.

## Migration Plan

- Greenfield on `main-tony-v1.0`; no data migration. Rollback = revert commits.

## Open Questions

- None blocking. Exact pinned versions of `claude-agent-sdk` and `mcp` are chosen at implementation time (latest compatible at that moment).
