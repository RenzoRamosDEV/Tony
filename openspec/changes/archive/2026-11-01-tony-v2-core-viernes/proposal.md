# Proposal

## Why

Tony v2 is rebuilt from an empty branch around three agents with fixed roles: Jarvis (`front`), Viernes (`worker`) and Edith (`guard`). Nothing can be built on top until the core exists: a validated way to declare agents and their MCP tools, a manager that owns every MCP connection, a single guarded execution path for tool calls, and a way to run the worker end to end and audit what it did. This change delivers that core and proves it by running Viernes from the CLI.

## What Changes

- Python 3.12 project skeleton managed with `uv` (package `tony`, console script `tony`), source layout `tony/core/{config,loader,mcp,orchestrator,guard,voice,events,memory,logging}` and `tony/apps/{cli,desktop}`, root data folders `agents/`, `config/`, `memory/`, `logs/`, `evals/`, `packaging/`, a `README.md` stub, and an offline-by-default test setup (pytest, pytest-asyncio, pytest-timeout 30 s, ruff line length 100, `evals` and `voice` markers).
- Agent definition loader: `agents/<name>/agent.md` (strict YAML frontmatter + Markdown system prompt) and `agents/<name>/tool/tool.json` (`mcpServers` + `native`), with errors that name file and field; `allow`/`confirm` keys are rejected anywhere in `tool.json` because permissions belong to `agents/edith/policy.yaml`.
- `config/tony.yaml` settings with documented defaults and model aliases (`claude-haiku` -> `claude-haiku-5-5`, `claude-sonnet` -> `claude-sonnet-5-5`); secrets only in `config/.env`, `${VAR}` placeholders resolved only when an MCP starts, never leaked to prompts, tool results or logs.
- MCP manager over the official `mcp` SDK: stdio and streamable-HTTP servers, 10 s connect timeout per server, failed servers logged and skipped, tool ids `<server>.<tool>` and `tony.<name>` for native tools.
- Tool proxy: every agent tool call `{task_id, agent, tool, args}` passes through a `Guard` port (`allow | confirm | deny`) and runs with a 20 s timeout. The only Guard in this phase is `AllowAllGuard`.
- Worker execution on the Claude Agent SDK with Tony-owned in-process proxy MCP tools; built-in Claude Code tools disabled; any non-proxied tool name denied.
- `tony run <agent> "<task>"`: structured task in (`objetivo`, `contexto`, `restricciones`), structured JSON result out (`resumen`, `datos`, `pasos`, `errores`), 300 s task timeout.
- Per-task JSONL audit log at `logs/tasks/<task_id>.jsonl`.
- Bundled `agents/viernes/` (`agent.md`, `tool/tool.json`).

## Capabilities

### New Capabilities
- `agent-definitions`: schema and validation of `agent.md` frontmatter/prompt and `tool/tool.json` for an agent folder.
- `tony-config`: `config/tony.yaml` schema and defaults, model alias resolution, secrets from `config/.env` and `${VAR}` placeholder resolution rules.
- `mcp-connections`: connecting declared MCP servers (stdio / streamable HTTP), failure isolation, and tool id naming.
- `tool-proxy`: the guarded, time-bounded execution path every agent tool call takes, and the `Guard` contract.
- `worker-tasks`: structured task/result contract, running a worker agent on the Claude Agent SDK with only proxied tools, task timeout, and the `tony run` CLI.
- `task-log`: per-task JSONL event log format and event types.

### Modified Capabilities
- None (no main specs exist yet).

## Impact

- New code under `tony/` and `tests/`; new `pyproject.toml`, `uv.lock`, `README.md`, `config/tony.yaml`, `config/.env.example`, `agents/viernes/`.
- Runtime dependencies: `claude-agent-sdk`, `mcp`, `pydantic`, `pydantic-settings`, `pyyaml`, `typer`. Dev: `pytest`, `pytest-asyncio`, `pytest-timeout`, `ruff`, `mutmut`.
- External: `npx` / Node for the real `@modelcontextprotocol/server-filesystem` (only in `evals`); Claude credentials only for `evals` and real runs.
- Out of scope: Jarvis, real Edith policy/confirmation/audit, voice, desktop app, memory, scheduler, any web UI, engines other than the Claude Agent SDK, `tony doctor`.
