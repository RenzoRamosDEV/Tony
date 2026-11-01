# Proposal

## Why

Every proxied tool call currently reaches the real MCP through an allow-all guard, so Viernes can write, delete or run shell commands with no policy, no user confirmation and no trace. Edith, the `guard` agent, must replace it with a deterministic, auditable permission policy before any front agent or desktop app is built on top. A phase-01 masking defect is also fixed here: every value resolved from a `${VAR}` placeholder is masked, so non-secret values such as `${HOME}` turn real paths into `***/notas/...`.

## What Changes

- Ship `agents/edith/` (`agent.md` with role `guard`, model `claude-haiku`, very formal Spanish persona, voice `kokoro/ef_dora`; `policy.yaml`). A `guard` agent has no `tool/` folder and the loader rejects one that does.
- Add a pydantic policy schema (`default`, ordered `rules` with `match`/`verdict`/`id`/`when`, `limits`, `auth`) and a deterministic, model-free evaluator (case-sensitive `fnmatch`, first match whose `when` conditions all hold, `path_outside` / `args_regex` / `numeric_above`).
- Add `EdithGuard`: evaluates the policy for every proxied call (MCP and native `tony.*`), asks the user on `confirm` through a confirmation channel with a model-worded question (deterministic template fallback after failure or 5 s), and appends one audit line per verdict to `logs/audit.jsonl`.
- **BREAKING** Guard port returns a ruling (`verdict`, `rule`, `user_decision`) instead of a bare decision; `AllowAllGuard` is removed and Edith becomes the default guard of `tony run`.
- Denied calls return `{"error": "blocked_by_policy", "rule": "<rule id>"}` to the agent; the 3rd denial of the same tool in a task, a confirmation answered no / anything else / timed out, or exceeding the per-agent step limit cancels the whole task with an explanatory `errores` entry.
- Task and tool timeouts come from the policy `limits`; a `token_alert` event is logged once per task when total tokens exceed `limits.token_alert`.
- `tony run` confirms on the terminal (question on stderr, answer on stdin; `s`/`si`/`sí`/`y`/`yes` mean yes).
- New `tony audit [--today] [--verdict allow|confirm|deny]` printing audit lines as a table.
- `evals/politica.yaml` with 20+ cases against the shipped policy, run offline by the default pytest suite.
- Fix: only values defined in `config/.env`, and values of placeholders whose variable name looks secret, are masked; `${HOME}` and other process variables are resolved but not masked.

## Capabilities

### New Capabilities
- `guard-policy`: Edith's agent folder, the `policy.yaml` schema, the deterministic evaluation algorithm, the shipped example policy and its offline policy evals.
- `guard-confirmation`: how verdicts are enforced on a call (allow / deny result / confirm), the confirmation channel contract, question wording with fallback, and the CLI confirmation channel.
- `guard-audit`: the `logs/audit.jsonl` line format, argument hashing and masked previews, and the `tony audit` command.
- `task-supervision`: per-task limits enforced around a worker run: denial counter, step counter, token alert and task cancellation.

### Modified Capabilities
- `agent-definitions`: `tool/tool.json` is required only for non-guard agents; a `guard` agent with a `tool/` folder is rejected; Edith is a bundled agent.
- `tool-proxy`: guard contract returns a ruling; `confirm` is resolved through confirmation instead of always failing; the allow-all guard requirement is removed; denied result format; tool timeout from policy limits.
- `tony-config`: secret definition narrowed to `config/.env` values and secret-looking variable names; masking no longer applies to every resolved placeholder.
- `task-log`: secret-masking scenario aligned with the narrowed secret definition; new `token_alert` event and `cancelled` outcome.
- `worker-tasks`: task timeout from policy limits; `tony run` uses Edith with CLI confirmation.

## Impact

- Code: `tony/core/guard/` (policy, evaluator, Edith, confirmation, wording, audit), `tony/core/orchestrator/` (proxy, runner, new supervisor), `tony/core/loader/agent.py`, `tony/core/config/{secrets,placeholders}.py`, `tony/core/mcp/manager.py`, `tony/core/events/`, `tony/apps/cli/main.py`.
- Data: new `agents/edith/`, `evals/politica.yaml`; runtime file `logs/audit.jsonl` (already gitignored via `logs/`).
- Tests: new fakes (confirmer, wording model), test homes must include `agents/edith/`; tests using `AllowAllGuard` move to the recording guard fake.
- Dependencies: none added (Claude Agent SDK already present for the wording adapter).
