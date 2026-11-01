# Design

## Context

- Phase 01 left a `Guard` port (`decide(ToolCall) -> Decision`) with `AllowAllGuard` as the only implementation, injected through `RunDeps.guard`. `ToolProxy` (`tony/core/orchestrator/proxy.py`) is the single path of every proxied call: log `tool_call` → guard → execute with `wait_for` → mask → log `tool_result`. Any non-`allow` decision returns a generic error text.
- `run_task` (`tony/core/orchestrator/runner.py`) wraps the engine in `asyncio.wait_for(task_timeout)`; there is no way to cancel a task from inside a tool call.
- `load_agent` always requires `tool/tool.json`; role `guard` is already accepted by the frontmatter schema.
- Masking defect: `load_secrets` merges `config/.env` and `os.environ` into one map; `resolve_placeholders` returns the resolved *values* used, and `McpManager._connect` registers all of them in `SecretMasker`. So `${HOME}` is masked everywhere.
- Constraints: offline default tests with fakes, no new dependencies, every message JSON-serializable, Edith decides without any model (< 5 ms), model only words questions.

## Goals / Non-Goals

**Goals:**
- Pure, model-free policy evaluation isolated from I/O so it is trivially testable and fast.
- Edith as a `Guard` adapter combining policy, confirmation and audit; task-level limits kept in the orchestrator.
- One cancellation mechanism shared by rejected confirmations, repeated denials and the step limit.

**Non-Goals:**
- PIN authentication / `auth` enforcement (the section is parsed and validated only; `config/edith.lock` stays unused).
- Subagents (the `agent` field just carries whatever name the envelope has; `<agent>/<subagent>` is produced by a later phase).
- Desktop/voice confirmation channels, LLM judging in Edith, front-agent explanation of cancellations (later phases consume `errores`).
- Symlink resolution in `path_outside` (see Risks).

## Decisions

### D1. Module layout (Ports and Adapters)

```
tony/core/guard/
  port.py        Guard protocol: decide(ToolCall) -> Ruling            (modified)
  policy.py      pydantic Policy/Rule/When/Limits/Auth + load_policy(root, guard)
  evaluate.py    evaluate(policy, tool, args) -> Verdict(verdict, rule)  (pure)
  confirm.py     Confirmer port, NoChannelConfirmer, CliConfirmer
  wording.py     QuestionWording port, template_question(), worded_question() with 5 s fallback
  claude_wording.py  ClaudeWording adapter (Claude Agent SDK, no tools)
  audit.py       canonical_json, args_hash, args_preview, AuditLog (append), read/filter for CLI
  edith.py       EdithGuard(policy, confirmer, wording, audit, masker, clock)
tony/core/orchestrator/
  supervisor.py  TaskSupervisor: steps, denials, cancel(reason), cancelled event
  proxy.py       uses Ruling + supervisor                                (modified)
  runner.py      builds Edith, supervisor, races engine vs cancel        (modified)
```
- `Ruling` (`verdict`, `rule`, `user_decision: "allow"|"deny"|"timeout"|None`) is a pydantic model in `tony/core/events/messages.py` next to `ToolCall`, keeping it JSON-serializable and dependency-free for the port.
- Alternative rejected: keep `Decision` and let the proxy evaluate/confirm. It would leak policy and confirmation into the orchestrator and duplicate Edith's responsibilities.

### D2. Split of responsibilities: Edith vs supervisor
- Edith: evaluate → (confirm: word + ask with `confirm_timeout_s`) → audit → return `Ruling`. Stateless across calls.
- `TaskSupervisor` (per task, from `policy.limits`): `step(agent)` before judging (exceed → cancel, no audit), `denied(tool, rule)` after a `deny` (reaching `max_denied_retries` → cancel), `cancel(reason)` on unconfirmed `confirm`, `record_usage(...)` → one `token_alert` event.
- Rationale: limits are task lifecycle concerns that also apply when another guard is injected in tests; Edith stays a pure guard adapter.

### D3. Proxy flow

```
tool_call event
  -> supervisor.step(agent)          cancelled? -> error reply (no guard, no audit)
  -> ruling = guard.decide(envelope)
       deny                      -> supervisor.denied(); reply {"error":"blocked_by_policy","rule":...}
       confirm & user != allow   -> supervisor.cancel(reason); error reply naming tool
       allow / confirm+allow     -> wait_for(caller.call, limits.tool_timeout_s)
  -> mask -> tool_result event
```
- The deny reply text is `json.dumps({"error": "blocked_by_policy", "rule": rule})` with `is_error=True`.

### D4. Task cancellation by racing
- `run_task` starts the engine as an `asyncio.Task` and waits on `{engine_task, supervisor.cancelled.wait()}` with `FIRST_COMPLETED` and the task timeout. On cancel: `engine_task.cancel()`, await it (suppress `CancelledError`), which unwinds `McpManager` and closes stdio processes; return `TaskResult(resumen="", errores=[reason])` and log `task_finished` outcome `cancelled`.
- Alternative rejected: raising from inside the tool handler. The Claude Agent SDK in-process MCP server converts handler exceptions into tool errors, so the model would keep going and could retry.
- Reasons (Spanish, user-facing in `errores`):
  - rejected: `tarea cancelada: el usuario no autorizó <tool> (regla <rule>)`
  - timeout: `tarea cancelada: sin respuesta a la confirmación de <tool> en <n> s (regla <rule>)`
  - denials: `tarea cancelada: <tool> bloqueada <n> veces por la política (regla <rule>)`
  - steps: `tarea cancelada: <agent> superó el límite de <n> pasos`

### D5. Confirmation channel and wording
- `Confirmer.ask(question: str) -> bool | None` (None = no answer); Edith applies `asyncio.wait_for(..., confirm_timeout_s)` → `timeout`; `False`/`None` → `deny`. `NoChannelConfirmer` returns `False` (default in `RunDeps`).
- `CliConfirmer(readline, err)`: writes the question to stderr; reads via a **daemon** thread that resolves an asyncio future with `call_soon_threadsafe`. A plain `asyncio.to_thread(input)` would block interpreter shutdown after a timeout because `asyncio.run` joins the default executor. `readline` is injected so tests never touch real stdin. Yes-set: `{"s","si","sí","y","yes"}` after `strip().casefold()`.
- `worded_question(wording, tool, preview, rule)`: `wait_for(wording.word(...), 5)`; result accepted only if it matches `^Acción: .+\. Regla: <re.escape(rule)>\. ¿Autoriza\?$` (single line); otherwise or on any exception → `template_question`. The model only ever receives the masked `args_preview`.
- `ClaudeWording`: one-shot `claude_agent_sdk.query` with `tools=[]`, `setting_sources=[]`, `max_turns=1`, Edith's body as system prompt and its resolved alias (`claude-haiku` → `claude-haiku-5-5`). Not covered by default tests (live model); a `FakeWording` covers the port. `tony run` wires `ClaudeWording`; a missing/failed model degrades to the template.

### D6. Policy evaluation details
- `fnmatch.fnmatchcase`. Paths: `os.path.abspath(os.path.expanduser(p))` and containment by `Path.is_relative_to` (equal counts as inside; `~/notasx` is outside). Directories expanded the same way at evaluation (not at load) so `HOME` can be faked in tests.
- `args_regex` compiled once at load (`field_validator` → load error on invalid regex).
- `numeric_above`: `isinstance(v, int | float) and not isinstance(v, bool) and v > value`.
- Policy evals: `evals/politica.yaml` is a YAML list; optional `extra_rules` per case are prepended to a copy of the shipped rules (shipped default/limits unchanged). Test sets `HOME` to a fixed fake directory with `monkeypatch`.

### D7. Audit
- Canonical JSON: `json.dumps(args, sort_keys=True, ensure_ascii=False)` (default separators `, `/`: `). `args_hash` hashes the raw canonical JSON; `args_preview` masks a deep copy first (secret-looking keys → `***`, then the shared `SecretMasker`), then truncates at 200 chars + `…`.
- `AuditLog(root, clock)` appends one line per call with `open("a")`; `duration_ms` from an injected monotonic clock, so tests are deterministic.
- `tony audit`: parses lines (malformed lines skipped with one stderr warning), filters by verdict and by local date using an injected aware `now()` (`ts` converted with `astimezone(now().tzinfo)`), prints a fixed-width plain-text table (no new dependency). Exit 0 always on success.

### D8. Secret definition fix
- `load_secrets` becomes `load_variables(root, environ) -> Variables(values, env_file_values, secret_names)`: `values` = `{**env_file, **environ}` (unchanged precedence); `secret_names` = names defined in `config/.env` ∪ names matching `SECRET_NAME = (?i)(token|key|secret|password|passwd|authorization|pin)`.
- `resolve_placeholders` returns the **names** used; `McpManager` registers `values[name]` only for `name in secret_names`.
- The runner creates the task's `SecretMasker` pre-registered with every non-empty `config/.env` value, shared by task log, proxy, audit and Edith. `SECRET_NAME` lives in `tony/core/config/secrets.py` and is reused for audit key masking.

### D9. Loader and runner wiring
- `load_agent`: role `guard` → reject `agents/<name>/tool/` if it exists, return empty `ToolSpec()`; other roles unchanged.
- `RunDeps`: replace `guard: Guard = AllowAllGuard` with `guard: Guard | None = None` (override for tests), add `confirmer: Confirmer = NoChannelConfirmer()`, `wording: QuestionWording | None = None` (None → template only), `monotonic`, and `task_timeout: float | None = None` (None → policy). The runner always loads `config.guard`'s agent and policy (fail fast, before any MCP connects).
- `AllowAllGuard` and its test are deleted; `RecordingGuard` fake returns a configurable `Ruling`.

## Risks / Trade-offs

- [`path_outside` does not resolve symlinks; a link inside `~/notas` pointing elsewhere is treated as inside] → Accepted for determinism and to avoid filesystem access in the guard; the filesystem MCP enforces its own roots.
- [Relative paths are normalised against Tony's cwd, not the MCP's root] → Errs toward `confirm` (outside), which is the safe direction.
- [`path_outside` does not hold when no path arg exists, so a pathless `filesystem.write_file` matches the later allow rule] → The MCP rejects such calls; documented in the policy evals.
- [Every `config/.env` value is masked by substring; a short or common value (e.g. `1`) would over-mask outputs] → `.env.example` states only secrets belong there; over-masking is the safe failure.
- [`args_hash` is computed over raw args that may include secrets] → SHA-256 is one-way; low-entropy secrets could be brute-forced from the hash. Accepted for correlation value; the audit file is local and gitignored.
- [Cancelling the SDK client mid-stream] → Covered by the fake engine path in tests; the real adapter relies on `async with` cleanup, verified by the existing process-exit test pattern.
- [Daemon reader thread may remain blocked on stdin after a timeout] → Harmless: daemon threads do not block exit; at most one pending reader exists per question.
- [BREAKING Guard port] → Only internal callers; all updated in the same change.

## Migration Plan

- Add `agents/edith/` in the same commit that makes the runner load it, so `tony run` never breaks between commits; test homes copy `agents/edith/`.
- Rollback: revert the change; no persistent data format other than the new append-only `logs/audit.jsonl`, which can be deleted.
