# Tasks

Every implementation task follows Red -> Green -> Refactor: write the named failing test(s) first, run them and confirm they fail for the expected reason, implement the minimum to pass, refactor (SRP, clear names), then run `uv run pytest` and `uv run ruff check`. Each numbered task is one atomic Conventional Commit (imperative, subject < 72 chars, no trailing period, no co-author or AI attribution lines). Default tests stay offline: fake model engine, fake wording model, fake confirmer, fake stdio MCP server; no real model and no real stdin.

## 1. Secret definition fix (`tony/core/config`, `tony/core/mcp`)

- [x] 1.1 Red: tests for `load_variables(root, environ)` returning merged `values` (process env overrides `config/.env`), `env_file_values` and `secret_names` (= `.env` names ∪ names matching `(?i)(token|key|secret|password|passwd|authorization|pin)`); boundaries: missing `.env`, empty value ignored, `HOME` not secret, `API_KEY` from environ secret, `PING` matches (documented over-masking); Green: replace `load_secrets` with `load_variables`, export `SECRET_NAME`; verify tests pass
- [x] 1.2 Red: tests that `resolve_placeholders` returns the set of variable **names** used (not values) and still raises `UndefinedVariableError` without leaking values; Green: implement; verify tests pass
- [x] 1.3 Red: integration tests with the fake stdio server: `${HOME}`-based arg resolved and NOT masked in `echo_env`/tool result and `tool_result` log event; `config/.env` `GITHUB_TOKEN=s3cr3t` used via `env` is masked; `.env` value never used by any server still masked in a tool result (masker pre-registered by the runner); Green: `McpManager` registers only secret names' values, runner seeds the task `SecretMasker` with all non-empty `.env` values; update `config/.env.example` comment ("only secrets: every value here is masked"); verify tests pass and the phase-01 masking tests still pass

## 2. Shared models and test doubles

- [x] 2.1 Red: tests for `Ruling` (`verdict`, `rule`, `user_decision` in `allow|deny|timeout|None`) JSON round-trip and invalid `user_decision` rejected; Green: add pydantic `Ruling` to `tony/core/events/messages.py`; verify tests pass
- [x] 2.2 Red: tests for new event builders `token_alert(total_tokens, limit)` and `task_finished` with outcome `cancelled` (JSON-serializable); Green: implement in `log_events`; verify tests pass
- [x] 2.3 Red: tests for fakes: `FakeConfirmer` (scripted answers `True`/`False`/`None`/hang, records questions), `FakeWording` (scripted text, raise, or delay; records inputs); fake fs server gains `write_file` and `delete_file` (rooted, path escape rejected); Green: implement in `tests/fakes/`; verify tests pass

## 3. Policy schema and loader (`tony/core/guard/policy.py`)

- [x] 3.1 Red: tests for `Policy` schema: `default` required and in `allow|confirm|deny`; `rules` default `[]`; `limits` and `auth` defaults; unknown keys rejected at every level with dotted field (`limits.max_cost`, `rules.1.verdict`); Green: implement pydantic models with `extra="forbid"`; verify tests pass
- [x] 3.2 Red: tests for `Rule`: `match` string or non-empty list (empty list rejected), derived id `<first pattern>/<verdict>`, explicit `id`, `when` with `path_outside` list, `args_regex` compiled at load (invalid regex -> error at `rules.<n>.when.args_regex`), `numeric_above {arg, value}`; Green: implement; verify tests pass
- [x] 3.3 Red: tests for `load_policy(root, guard)` reading `agents/<guard>/policy.yaml`: missing file, invalid YAML, non-mapping, schema error -> `DefinitionError` naming the file and field; Green: implement; verify tests pass

## 4. Deterministic evaluation (`tony/core/guard/evaluate.py`)

- [x] 4.1 Red: tests for first-match ordering, list patterns, case-sensitive `fnmatchcase` (`Filesystem.read_file` -> default), default verdict with rule id `default`, rule whose pattern matches but `when` fails falls through; Green: implement `evaluate(policy, tool, args) -> Verdict(verdict, rule)`; verify tests pass
- [x] 4.2 Red: tests for `path_outside` with `HOME` monkeypatched: inside, equal to dir, `~` expansion, `..` escape, sibling prefix `~/notasx`, `source`/`destination`/`paths` keys, non-string values ignored, no path arg -> does not hold; Green: implement; verify tests pass
- [x] 4.3 Red: tests for `args_regex` (hit at top level, nested dict/list hit, keys ignored, miss) and `numeric_above` (equal -> no, above int/float -> yes, bool/string/missing -> no); Green: implement; verify tests pass
- [x] 4.4 Red: latency test: mean of 1000 evaluations against the shipped policy < 5 ms; verify it passes (no implementation change expected; refactor only if it fails)

## 5. Edith agent, shipped policy and policy evals

- [x] 5.1 Red: tests that a `guard` agent with a `tool/` folder is rejected naming `agents/<name>/tool/`, and a `guard` agent without it loads with empty `ToolSpec`; worker without `tool.json` still fails; Green: update `load_agent`; verify tests pass
- [x] 5.2 Red: tests that bundled `agents/edith/` loads (role `guard`, model `claude-haiku`, persona `es` / `muy formal, neutral, literal, sin humor`, voice `kokoro/ef_dora`, no tools) and that bundled `policy.yaml` equals the shipped example policy (rule ids, verdicts, conditions, limits, auth) and its default is not `allow`; Green: write `agents/edith/agent.md` (system prompt: answer only `Acción: <qué>. Regla: <rule id>. ¿Autoriza?` in formal Spanish, never add text) and `agents/edith/policy.yaml` exactly as specified; verify tests pass
- [ ] 5.3 Red: offline test `tests/core/guard/test_policy_evals.py` loading `evals/politica.yaml`, asserting >= 20 cases, verdict set `{allow, confirm, deny}`, and each case's verdict (optional `extra_rules` prepended to the shipped rules; `HOME` monkeypatched); Green: write `evals/politica.yaml` with >= 20 cases covering: read/list allow, write inside `~/notas` and `~/proyectos`, write equal to `~/notas`, write `/tmp/a.md`, `~/notas/../secretos/x.md`, `~/notasx/a.md`, delete/move confirm (list pattern), `shell.run` with `sudo`, `rm -rf`, `curl x | sh` deny, `shell.run ls` confirm (ordering), `github.search_code` allow vs `github.create_issue` confirm (ordering), `tony.read_skill`/`tony.run_subagent` allow, unknown tool default confirm, case-sensitive id default, numeric equal (default) and above (deny) via `extra_rules`; verify the test passes

## 6. Audit trail (`tony/core/guard/audit.py`)

- [ ] 6.1 Red: tests for `canonical_json` and `args_hash` (key order irrelevant, SHA-256 hex of `{"a": 2, "b": 1}`, non-ASCII kept); Green: implement; verify tests pass
- [ ] 6.2 Red: tests for `args_preview`: secret-looking keys masked (nested too), `.env` values masked via `SecretMasker`, `HOME` path unmasked, truncation at exactly 200 (unchanged) vs 201 (200 chars + `…`); golden-file test for the confirmed-delete audit line (`tests/golden/audit_confirm.jsonl`) with injected clock; Green: implement `args_preview` and `AuditLog.append` (creates `logs/`, one line per call, fields `ts, task_id, agent, tool, args_hash, args_preview, verdict, rule, user_decision, duration_ms`); verify tests pass

## 7. Confirmation and wording (`tony/core/guard/confirm.py`, `wording.py`)

- [ ] 7.1 Red: tests for `template_question(tool, preview, rule)` exact text and `worded_question`: valid model text used; model raising, exceeding injected 5 s timeout (short in tests), multi-line, wrong rule or off-template text -> template; model input contains `***` not the secret; Green: implement `QuestionWording` port and `worded_question`; verify tests pass
- [ ] 7.2 Red: tests for `CliConfirmer` with injected `readline` and `StringIO` stderr: ` Sí `, `YES`, `s`, `si`, `y` -> `True`; `vale`, empty line, EOF (`""`/`None`) -> `False`; question written to stderr only; a never-returning `readline` under an outer `wait_for` does not keep the loop or interpreter from finishing (daemon thread); `NoChannelConfirmer` -> `False`; Green: implement; verify tests pass
- [ ] 7.3 Implement `ClaudeWording` adapter (one-shot Claude Agent SDK `query`, `tools=[]`, `setting_sources=[]`, `max_turns=1`, Edith's system prompt and resolved model id) test-first with a fake SDK `query` callable asserting options and returned text; add an `evals`-marked test with the real model asserting the returned question matches the template; verify the default run skips it

## 8. Edith guard (`tony/core/guard/edith.py`)

- [ ] 8.1 Red: tests for `EdithGuard.decide` with fakes: `allow` and `deny` rulings with `user_decision=None`, no confirmer call; one audit line each with exact fields and `duration_ms` from an injected monotonic clock; Green: implement; verify tests pass
- [ ] 8.2 Red: tests for `confirm`: question asked with worded text; yes -> `user_decision="allow"`; no / other -> `deny`; confirmer hanging past injected `confirm_timeout_s` -> `timeout`; audit line written after the answer with `duration_ms` including the wait; Green: implement; verify tests pass

## 9. Supervision and proxy (`tony/core/orchestrator`)

- [ ] 9.1 Red: tests for `TaskSupervisor`: steps per agent (30th ok, 31st cancels with reason naming agent and limit), denials per tool id (3rd of same tool cancels with tool/count/rule; 2+2 different tools do not), `cancel()` sets the event once and keeps the first reason, `record_usage` emits exactly one `token_alert` above the limit (50001) and none at 50000; Green: implement; verify tests pass
- [ ] 9.2 Red: switch the `Guard` port to `decide(ToolCall) -> Ruling` (`RecordingGuard` returns a configurable `Ruling`; `AllowAllGuard` returns `Ruling(verdict="allow", rule="allow_all")` until 10.1 removes it) and write proxy tests: deny reply is exactly `{"error": "blocked_by_policy", "rule": "<rule>"}` with `is_error` and caller not invoked; confirm+allow executes; confirm+deny/timeout not executed, error reply names the tool and supervisor cancelled; step overflow skips the guard; tool timeout taken from `limits.tool_timeout_s` and counted after confirmation; `tool_call`/`tool_result` events still logged in order; Green: update `ToolProxy`; verify tests pass

## 10. Runner and CLI wiring

- [ ] 10.1 Red: update `make_viernes_home` to copy `agents/edith/` (and allow a custom policy); runner tests: Edith is the default guard (loaded from `config.guard`), invalid/missing policy fails before any MCP connects, task timeout from `limits.task_timeout_s` unless overridden; Green: delete `AllowAllGuard` and its test; update `RunDeps` (`guard` override, `confirmer`, `wording`, `monotonic`, `task_timeout: float | None`) and `run_task`; verify tests pass
- [ ] 10.2 Red: offline acceptance tests with `FakeModelEngine` + fake fs server + shipped policy: write inside `~/notas` allowed (one audit line); delete confirmed by `FakeConfirmer` runs; delete rejected cancels (`errores` names tool and rule, no later scripted call executed, `task_finished` outcome `cancelled`, stdio process exited); confirmation timeout -> audit `user_decision: "timeout"`; third denied `shell.run` (fake server exposing `shell.run`) cancels; `default: deny` policy blocks `foo.bar` with audit `rule: default`; token total 50001 logs one `token_alert`; Green: implement the cancel race in `run_task`; verify tests pass
- [ ] 10.3 Red: CLI tests for `tony run` with injected engine, wording and `readline` factories: question on stderr, stdout only JSON; answer `s` executes, `no` exits 1 with cancellation in `errores`; invalid policy exits 2 naming the file and field; Green: wire `CliConfirmer` and `ClaudeWording` as defaults in `create_app`; verify tests pass
- [ ] 10.4 Red: CLI tests for `tony audit` with a temp `TONY_HOME` and injected aware `now()` (UTC+1): header and columns `ts, agent, tool, verdict, rule, user_decision`; `--verdict deny` filter; `--today` local-date boundary (`2026-10-31T23:30:00Z` kept, `2026-10-31T22:30:00Z` dropped); missing file -> header only, exit 0; malformed line skipped with a stderr warning; `--verdict maybe` exits non-zero; Green: implement; verify tests pass and `uv run tony --help` lists `audit`
- [ ] 10.5 Document Edith (`agents/edith/policy.yaml` schema and evaluation order, confirmation answers, `logs/audit.jsonl`, `tony audit`, what counts as a secret) in `README.md`; verify `uv run tony audit --help` works as written

## 11. Final verification

- [ ] 11.1 Run `uv run pytest` (offline, no `evals`/`voice`) and `uv run ruff check` and `uv run ruff format --check`; verify all pass, `evals/politica.yaml` test included, and no test exceeds the 30 s timeout
- [ ] 11.2 Mutation testing scoped to this change's diff, each run wrapped in `timeout 180`, split by module: `timeout 180 uv run mutmut run "tony.core.guard.policy*" "tony.core.guard.evaluate*"`, then `"tony.core.guard.audit*" "tony.core.guard.edith*"`, then `"tony.core.guard.confirm*" "tony.core.guard.wording*"`, then `"tony.core.orchestrator.supervisor*" "tony.core.orchestrator.proxy*" "tony.core.orchestrator.runner*"`, then `"tony.core.config.secrets*" "tony.core.config.placeholders*" "tony.core.loader.agent*" "tony.apps.cli.main*"`; add `agents/edith/` and `evals/` to `also_copy` and `do_not_mutate` for the live `ClaudeWording` SDK call; verify each module's score > 95% via `uv run mutmut results` or record each surviving mutant with justification in the commit body; abort and split further if any run hits the 180 s limit
- [ ] 11.3 Grep the change's files, `logs/` and `logs/audit.jsonl` produced by the test suite for every secret value used in tests (e.g. `s3cr3t`, `abc123`, `k3y`); verify none found

## Workflow follow-up

- Archive the change after review with the openspec archive workflow.
