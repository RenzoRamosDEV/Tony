## 1. Evidence core (tests first)

- [x] 1.1 Write failing tests `tests/core/evidence/test_validate_sources.py`: exact excerpt kept; whitespace/newline differences kept; case difference dropped; invented dropped with warning naming the title; empty or whitespace excerpt dropped; 300 characters valid and 301 invalid; entry not an object or lacking a field dropped with `entrada <n> no válida`; title cut at 80 characters in the warning; no observed texts drops all. Verify: tests fail with import error.
- [x] 1.2 Create `tony/core/evidence/{__init__,source,validate}.py` (`Source`, `SourceCheck`, `validate_sources`) until 1.1 passes; refactor for single responsibility. Verify: `pytest tests/core/evidence/test_validate_sources.py`.
- [x] 1.3 Write failing tests `tests/core/evidence/test_apply_and_render.py`: `apply_evidence` leaves a result without `fuentes` (or with list/text `datos`, or `datos` null) unchanged; replaces `fuentes` with kept sources; appends warnings to `pasos` and not `errores`; removes non-list `fuentes` with `fuentes ignoradas: no es una lista`; does not mutate the input; `ObservedTexts` append-only; `source_lines` returns `[]`, or `Fuentes:` plus `- connector · title` lines, skipping invalid entries. Verify: fail.
- [x] 1.4 Implement `observed.py`, `apply.py`, `render.py` in `tony/core/evidence/`. Verify: 1.3 passes.

## 2. Proxy records observed results (tests first)

- [x] 2.1 Write failing tests `tests/core/orchestrator/test_proxy_observed.py` with the existing fake guard/caller: successful MCP result recorded; recorded text is the capped text with marker; error reply, denied call, unconfirmed call, argument-changed call record nothing; `tony.read_skill` and `tony.ask_user` results not recorded; no `observed` given keeps current behaviour; `tony.ask_user` is not cut by `tool_timeout_s` (fake caller sleeps longer than a small timeout). Verify: fail.
- [x] 2.2 Add optional `observed` to `ToolProxy`, record in `call` after masking/capping for non-error non-`tony.` replies, add `tony.ask_user` to `UNTIMED_TOOLS`. Verify: 2.1 plus `tests/core/orchestrator/test_proxy*.py` pass.

## 3. Runner validates evidence (tests first)

- [x] 3.1 Write failing tests `tests/core/orchestrator/test_runner_evidence.py` using the fake engine/servers: a worker that calls an MCP tool and returns one real and one invented source gets only the real one back, with one warning in `pasos`, `errores` empty and outcome `ok`; the published `result` event and the task log carry the validated result; a source taken from a subagent's tool result is kept for the parent; a source quoting only `tony.read_skill` text is dropped; a result without `fuentes` is byte-identical to today; masked secret in excerpt still matches. Verify: fail.
- [x] 3.2 Add `observed` to `_TaskRun`, pass it in `_proxied_tools`, call `apply_evidence` in `_engine_result` after masking. Verify: 3.1 and the existing `tests/core/orchestrator/` runner tests pass.

## 4. Clarification core (tests first)

- [x] 4.1 Add fake `tests/fakes/clarify.py` (`FakeClarifier` scripted answers with a `HANG` marker, records requests). Write failing tests `tests/core/clarification/test_broker.py`: publishes one `clarification_requested` with request_id/task_id/agent/question/options; matching `answer` resolves; unknown id, stale id, no pending and second answer are ignored; `cancel()` resolves `None`; late answer after cancel/timeout ignored; second ask waits for the first (lock); a `needs_confirmation` event is never published. Verify: fail.
- [x] 4.2 Write failing tests `tests/core/clarification/test_cli.py`: `parse_answer` partitions (blank, `None`, `"1"`, `"2"`, `"0"`, `"7"`, `"-1"`, text, text with spaces, no options with `"1"`); `CliClarifier` prints `Viernes: question` and `1) a` / `2) b` on the err stream and returns the parsed answer; reading through `ConsoleLines` leaves a line typed after a timeout for the next reader. Verify: fail.
- [x] 4.3 Write failing tests in `tests/core/events/test_core_events.py` (event shape, `options` `[]`, JSON round trip, secret masked by `MaskingPublisher`) and `tests/core/orchestrator/test_commands.py` (`answer_clarification` parses; missing `answer` -> `InvalidCommand` naming the field but not the value; extra field rejected). Verify: fail.
- [x] 4.4 Create `tony/core/clarification/{__init__,request,port,broker,cli}.py`, add `core_events.clarification_requested` and `commands.AnswerClarification` to the `Command` union. Verify: 4.1-4.3 pass.

## 5. `tony.ask_user` native and runner binding (tests first)

- [x] 5.1 Write failing tests `tests/core/orchestrator/test_natives_ask_user.py`: valid call returns the answer; blank/missing/non-string `question` and non-list or non-string `options` are error results and the clarifier is not called; `None` from the scope -> error `no answer from the user`; scope without `ask_user` -> error; `NATIVE_TOOLS` contains `ask_user`. Verify: fail.
- [x] 5.2 Write failing tests `tests/core/orchestrator/test_runner_clarification.py` (fake clarifier, small `confirm_timeout_s` via a policy fixture): answer flows back and the same task finishes; the pending question is published with the asking agent's id; timeout returns the error and the task is not cancelled and `denied`/`unconfirmed` are not triggered; supervisor cancellation and user cancel end the wait; default `NoChannelClarifier` returns `no answer from the user` at once; blank answer is no answer; the worker's next `confirm`-rule call still asks for confirmation after an answer (answer never approves); call is judged `allow` under the shipped policy with a `tool_call` event and one audit line; a 30 s-style slow answer beyond `tool_timeout_s` still returns (use scaled-down limits). Verify: fail.
- [x] 5.3 Add `ask_user` factory to `natives.py` and `NATIVE_TOOLS`, optional `ask_user` to `NativeScope`, `RunDeps.clarifier` (default `NoChannelClarifier`), and `_ask_user` plus its use in `_bind_natives` in `runner.py`. Verify: 5.1-5.2 pass.

## 6. Policy and bundled agents (tests first)

- [x] 6.1 Write failing tests: extend `tests/core/guard/test_bundled_edith.py` (or the shipped-policy tests) so `tony.ask_user` is `allow` and the repo `agents/edith/policy.yaml` equals `SHIPPED_POLICY_YAML` (update the expected rule count where asserted); update `tests/core/loader/test_bundled_agents.py` so Viernes declares `["read_skill", "run_subagent", "ask_user"]` and its catalog has `tony.ask_user`; add tests that `evidencia` is listed without errors, its frontmatter is valid, and its body names `fuentes`, `connector`, `id`, `title`, `retrieved_at`, `excerpt`, `300`. Verify: fail.
- [x] 6.2 Add the rule `{match: tony.ask_user, verdict: allow}` right after the `tony.read_skill`/`tony.run_subagent` rule in `agents/edith/policy.yaml` and the identical entry in `tests/core/guard/shipped_policy.py`; add `"ask_user"` to `native` in `agents/viernes/tool/tool.json`; create `agents/viernes/skills/evidencia/SKILL.md` in Spanish as described in design D8. Verify: 6.1 and the guard/loader test directories pass.

## 7. Runtime wiring (tests first)

- [x] 7.1 Write failing tests in `tests/core/orchestrator/test_runtime.py` / `test_runtime_clarification.py` using `fake_runtime`: a delegated task calling `tony.ask_user` publishes `clarification_requested`; submitting `answer_clarification` completes the task; `confirm` does not resolve it and `answer_clarification` does not resolve a pending `needs_confirmation`; `cancel` ends the wait with the error; wrong `request_id` ignored; invalid command error does not echo the answer. Verify: fail.
- [x] 7.2 In `CoreRuntime` create `self.clarifications = ClarificationBroker(self._publish)` after the broker, pass `clarifier=` in `RunDeps`, route `AnswerClarification` in `_dispatch`, call `clarifications.cancel()` in `_cancel_turn`. Verify: 7.1 passes.

## 8. CLI wiring (tests first)

- [x] 8.1 Write failing tests: `tests/apps/test_cli_chat.py` (delegated task asks with options, user types `2`, option text reaches the tool, question and numbered options on stderr prefixed `Viernes: `, a later message line is not lost after a timed-out question, `Fuentes:` / `- gmail · Factura` on stdout after a task result with sources, nothing for a result without); `tests/apps/test_cli_run.py` (stdout is exactly the result JSON, `Fuentes:` on stderr, no extra line without sources; question answered from stdin). Verify: fail.
- [x] 8.2 Pass `clarifier=CliClarifier(...)` in `main.chat` (console) and `main.run` (thread reader); handle `result` scope `task` in `ChatPrinter`; print `source_lines` to stderr in `run`. Verify: 8.1 passes.

## 9. Regression and quality gates

- [x] 9.1 Run the full suite (`pytest -q`) and confirm no test over 10 s and none hanging; fix any regression without removing or renaming existing commands, tools, events, config keys or the four-field result. Verify: full suite green.
- [x] 9.2 Run mutation testing only on the diff (new `tony/core/evidence/`, `tony/core/clarification/`, and the changed lines in `natives.py`, `proxy.py`, `runner.py`, `runtime.py`, `chat.py`); target above 95 %, aborting after 3 minutes and falling back to targeted manual mutants (for example flip the `tony.` filter, the 300 limit, whitespace normalisation, the number-selection bounds, the lock, the cancel race); justify survivors. Verify: report of score and survivors in the PR description.
- [x] 9.3 Run `openspec validate clarification-and-evidence` and `ruff`/type checks used by the repo on touched files. Verify: all pass.
