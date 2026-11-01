# Tasks

Every implementation task follows Red -> Green -> Refactor: write the named failing test(s) first, confirm they fail, implement the minimum to pass, refactor, then run `uv run pytest` and `uv run ruff check`. Each numbered task is one atomic Conventional Commit.

## 1. Project skeleton and test harness

- [x] 1.1 Create `pyproject.toml` (package `tony`, Python `>=3.12,<3.13`, hatchling, console script `tony = "tony.apps.cli.main:app"`; deps `claude-agent-sdk`, `mcp`, `pydantic`, `pydantic-settings`, `pyyaml`, `typer`; dev group `pytest`, `pytest-asyncio`, `pytest-timeout`, `ruff`, `mutmut`), `.python-version`, pytest config (`asyncio_mode=auto`, `timeout=30`, markers `evals`/`voice`, `addopts="-m 'not voice'"`), ruff config (line length 100, py312); run `uv sync` and verify `uv.lock` is created
- [x] 1.2 Create package layout `tony/core/{config,loader,mcp,orchestrator,guard,voice,events,memory,logging}/__init__.py`, `tony/apps/{cli,desktop}/__init__.py`, root folders `agents/`, `config/`, `memory/`, `logs/`, `evals/`, `packaging/` (with `.gitkeep` where empty), `README.md` stub, `config/.env.example`; add `tests/test_layout.py` asserting every package imports and every folder exists; verify it passes
- [x] 1.3 Add `tests/conftest.py` that skips `evals`-marked tests unless `TONY_EVALS=1`; add a test proving an `evals`-marked dummy test is skipped without the variable; verify `uv run pytest` and `uv run ruff check` pass
- [x] 1.4 Verify the existing `.gitignore` contains every required entry (`requirements/`, `.claude/`, `.serena/`, `apm_modules/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `mutants/`, `config/.env`, `config/edith.lock`, `config/engine-auth.json`, `logs/`, `memory/*.sqlite*`, `memory/preferences.md`, `memory/settings.json`, `evals/runs/`, `samples/`) via `tests/test_gitignore.py`; verify it passes

## 2. Shared message models (`tony/core/events`)

- [x] 2.1 Red: tests for `TaskRequest` (non-empty `objetivo`, defaults `contexto=""`, `restricciones=[]`), `TaskResult` (`resumen`, `datos`, `pasos`, `errores`), `ToolCall` envelope `{task_id, agent, tool, args}` and `Decision` literal, including JSON round-trip and boundary cases (empty/whitespace `objetivo`); Green: implement pydantic models; verify tests pass

## 3. Configuration (`tony/core/config`)

- [x] 3.1 Red: tests for `TonyConfig` defaults (missing file), partial merge (`reply_mode: text` only), invalid `reply_mode`, unknown key, error naming `config/tony.yaml` and field; Green: implement loader with `extra="forbid"` and `DefinitionError(file, field, message)`; verify tests pass
- [x] 3.2 Red: tests for model alias resolution (`claude-sonnet` -> `claude-sonnet-5-5`, unknown alias error); Green: implement; verify tests pass
- [x] 3.3 Red: tests for `Secrets` from `config/.env` (missing file allowed, values readable) and root dir via `TONY_HOME`; Green: implement with pydantic-settings; verify tests pass
- [x] 3.4 Red: tests for `${VAR}` placeholder resolution (string, list, dict; multiple vars; undefined var error naming the var and not leaking values; literal text without placeholders unchanged) and `SecretMasker` (replaces each registered value with `***` in strings and nested JSON; ignores empty values); Green: implement; verify tests pass

## 4. Agent definitions (`tony/core/loader`)

- [ ] 4.1 Red: tests for `agent.md` parsing (valid file, missing frontmatter, empty body, invalid YAML) with errors naming the file; Green: implement frontmatter splitter; verify tests pass
- [ ] 4.2 Red: tests for frontmatter schema (each required field missing, `name` != folder, invalid `role`, unknown top-level and nested field, `voice.tts` boundaries `kokoro/x` ok vs `em_alex` / `kokoro/` rejected, alias not in configured models) asserting dotted field names; Green: implement `AgentSpec`; verify tests pass
- [ ] 4.3 Red: tests for `tool.json` schema (stdio+HTTP accepted, both/neither `command`/`url`, unknown keys, `native` default `[]`, invalid JSON, missing file, reserved server name `tony`, unknown native name against an injected native registry); Green: implement `ToolSpec`; verify tests pass
- [ ] 4.4 Red: tests that `allow`/`confirm` at top level and nested depth fail with dotted path and `agents/edith/policy.yaml` in the message; Green: implement recursive forbidden-key scan; verify tests pass
- [ ] 4.5 Red: test that the bundled `agents/viernes/` loads with default config (role `worker`, model `claude-sonnet`); Green: write `agents/viernes/agent.md` (Spanish persona, `kokoro/em_alex`, system prompt describing the structured task and result) and `agents/viernes/tool/tool.json` (filesystem server via `npx -y @modelcontextprotocol/server-filesystem ${HOME}/notas`, `native: []`); verify test passes

## 5. Task log (`tony/core/logging`)

- [ ] 5.1 Red: tests for task id (32 lowercase hex, unique) and `JsonlTaskLog` (creates `logs/tasks/`, appends one JSON object per line, `ts` UTC ISO 8601 via injected clock, `task_id`, `type`, applies `SecretMasker`); Green: implement; verify tests pass
- [ ] 5.2 Red: tests for typed event builders `task_started`, `tool_call`, `tool_result`, `token_usage`, `task_finished`, `error` (required fields present, JSON-serializable); Green: implement; verify tests pass

## 6. Test doubles

- [ ] 6.1 Red: test that spawns `tests/fakes/fake_fs_server.py` over stdio with the `mcp` client and lists `list_directory`, `read_file`, `sleep`, `echo_env`; Green: implement the fake stdio MCP server with the `mcp` SDK rooted at argv dir (path-escape rejected); verify test passes
- [ ] 6.2 Red: tests for `FakeModelEngine` (executes scripted tool calls in order through given handlers, records replies, returns scripted final answer and usage; fails clearly when a scripted tool id is not offered); Green: implement `tests/fakes/fake_engine.py`, plus `RecordingGuard` and `ListEventSink`; verify tests pass

## 7. MCP manager (`tony/core/mcp`)

- [ ] 7.1 Red: integration test connecting the fake stdio server and listing tools as `<server>.<tool>`; Green: implement `McpManager` async context manager with stdio transport and placeholder resolution at start; verify test passes
- [ ] 7.2 Red: tests for failure isolation (non-existent command, undefined `${VAR}`, server hanging past an injected short connect timeout) -> server marked down, `error` event + stderr line, other server tools available; Green: implement per-server `wait_for` (default 10 s) and status tracking; verify tests pass
- [ ] 7.3 Red: test with an in-process streamable-HTTP MCP server (local `mcp` SDK app on an ephemeral port) listing `remote.ping`; Green: implement HTTP transport with resolved headers; verify test passes
- [ ] 7.4 Red: tests for `call(tool_id, args)` (success content to text, MCP error result -> error reply, unknown id -> "not available") and that stdio processes exit after the context closes; Green: implement; verify tests pass
- [ ] 7.5 Red: tests for native tool registry (injected `now` tool exposed as `tony.now`, production registry empty); Green: implement; verify tests pass

## 8. Guard and tool proxy (`tony/core/guard`, `tony/core/orchestrator`)

- [ ] 8.1 Red: test `AllowAllGuard.decide` returns `allow` for any envelope; Green: implement `Guard` protocol and `AllowAllGuard`; verify test passes
- [ ] 8.2 Red: tests for `ToolProxy` with `RecordingGuard`: `allow` executes, `deny` and `confirm` do not execute and return error naming the tool, guard receives exact envelope, `tool_call`/`tool_result` events logged in order; Green: implement; verify tests pass
- [ ] 8.3 Red: tests for proxy timeout (fake server `sleep` beyond an injected short timeout -> error reply mentioning timeout, task continues), exception -> error reply, secret masking of `echo_env` result in reply and log; Green: implement `wait_for` (default 20 s) and masking; verify tests pass

## 9. Claude Agent SDK engine adapter (`tony/core/orchestrator`)

- [ ] 9.1 Red: unit tests for `build_options` (no built-in tools, `allowed_tools` only for the agent's proxy servers, resolved model id, system prompt = agent body, `setting_sources=[]`, structured output schema of `TaskResult`) and name mapping `mcp__<srv>__<tool>` <-> `<srv>.<tool>`; Green: implement; verify tests pass
- [ ] 9.2 Red: unit tests for `can_use_tool` (built-in `Bash` denied, malformed names denied, proxied name outside catalog denied, catalog name allowed) and result parsing (structured output -> `TaskResult`, invalid/missing -> unstructured error result with raw text in `resumen`), usage extraction to `token_usage`; Green: implement `ClaudeEngine`; verify tests pass

## 10. Task runner and CLI

- [ ] 10.1 Red: offline acceptance test: Viernes (temp `TONY_HOME` with copied agent whose `tool.json` points to the fake stdio server and a temp folder with `a.md`) run with `FakeModelEngine` scripted to call `filesystem.list_directory` then `filesystem.read_file`; asserts result uses both tools and the task log sequence `task_started`, `tool_call`/`tool_result` x2, `token_usage`, `task_finished`; Green: implement `run_task` (role check, log, manager, proxy, engine, close in `finally`); verify test passes
- [ ] 10.2 Red: tests for non-worker agent rejected, task timeout (injected short timeout, scripted engine hanging -> `errores` timeout, `task_finished`, server process exited), MCP down at start (extra server with non-existent command -> `error` event, run completes with filesystem tools); Green: implement; verify tests pass
- [ ] 10.3 Red: CLI tests with typer `CliRunner` and an injected engine factory: success prints single JSON object and exit 0, result with `errores` exits non-zero, unknown agent exits non-zero with folder name, invalid definition prints file+field on stderr; Green: implement `tony run <agent> "<task>"` in `tony/apps/cli/main.py`; verify tests pass and `uv run tony --help` lists `run`
- [ ] 10.4 Red: `evals`-marked test running Viernes with the real model and `@modelcontextprotocol/server-filesystem` over a temp folder, asserting a list-type and a read-type tool call in the log and a structured result; Green: wire `ClaudeEngine` as default engine factory; verify it is skipped by default and passes with `TONY_EVALS=1` when credentials and `npx` are available
- [ ] 10.5 Document setup, `config/tony.yaml`, `config/.env`, `agents/<name>/` layout and `tony run` usage in `README.md`; verify the documented `uv run tony run --help` command works as written

## 11. Final verification

- [ ] 11.1 Run `uv run pytest` (offline, no `evals`/`voice`) and `uv run ruff check` and `uv run ruff format --check`; verify all pass and no test exceeds the 30 s timeout
- [ ] 11.2 Configure `[tool.mutmut]` with `source_paths` limited to files added by this change, `do_not_mutate` for the SDK adapter's live client call and MCP transport opening code (justify: they need a subprocess/CLI unavailable in mutmut's copied tree); run `timeout 180 uv run mutmut run` and `uv run mutmut results`; verify mutation score > 95% or record each surviving mutant with justification in the commit body; abort and narrow scope if it exceeds 3 minutes
- [ ] 11.3 Grep the change's files and logs produced by the test suite for any resolved secret value used in tests; verify none found

## Workflow follow-up

- Archive the change after review with the openspec archive workflow.
