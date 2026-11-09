## Why

A worker that lacks one detail (which account, which file) today must guess or abort the task. And a worker's answer can claim facts with no way for the user to see where they came from. Two small slices fix this without touching Edith's safety model: ask the user mid-task, and back answers with sources that are verified against what the tools really returned.

## What Changes

- New native tool `tony.ask_user` `{question, options?}` returning the user's answer as text, so a task continues instead of restarting.
- New clarification broker, separate from the confirmation broker: event `clarification_requested{request_id, task_id, agent, question, options}`, core command `AnswerClarification{request_id, answer}`. An answer is never an approval.
- Wait bounded by `confirm_timeout_s`; on timeout, cancellation or no channel the tool returns the error `no answer from the user`.
- CLI (`tony chat`, `tony run`) prints the question and numbered options; a number selects an option.
- Shipped rule `{match: tony.ask_user, verdict: allow}` in `agents/edith/policy.yaml` and in the test copy of the shipped policy, identically. Viernes declares the native `ask_user`.
- New module `tony/core/evidence/`: `Source` model (excerpt at most 300 characters) and `validate_sources(sources, observed_texts)`.
- The tool proxy records the successful non-native tool result texts of each task; the task runner validates `datos.fuentes` against them before returning the result, dropping unsupported sources with a warning line in `pasos`.
- CLI prints `Fuentes:` with `- connector · title` lines after a result that has sources.
- Bundled Viernes skill `evidencia` (Spanish) teaching the worker to cite sources in that shape.

Nothing is removed or renamed. The four-field task result contract is unchanged; new event and command fields are additive. No permission is granted, no confirmation or PIN is bypassed, and every tool call still goes through the guard.

## Capabilities

### New Capabilities
- `task-clarification`: `tony.ask_user`, the clarification event/command pair, the bounded wait, and the guarantee that an answer never authorises anything.
- `answer-evidence`: source model, validation against observed tool results, per-task observed texts, validation in the runner, and the `Fuentes:` listing.

### Modified Capabilities
- `worker-tasks`: sources travel inside `datos.fuentes`; results are evidence-validated before returning.
- `task-supervision`: a clarification wait or timeout is neither a denial nor a cancellation.
- `core-events`: `clarification_requested` event and `answer_clarification` command.
- `chat-cli`: clarification prompt and answer parsing; `Fuentes:` list.
- `agent-skills`: bundled `evidencia` skill and its content.
- `guard-policy`: shipped policy gains the `tony.ask_user` allow rule; asking grants no permission.
- `tool-proxy`: observed result recording; `tony.ask_user` exempt from the per-call timeout.

## Impact

- New: `tony/core/clarification/`, `tony/core/evidence/`, `agents/viernes/skills/evidencia/SKILL.md`.
- Changed: `tony/core/orchestrator/{natives,runner,proxy,commands,runtime}.py`, `tony/core/mcp/native.py`, `tony/core/events/core_events.py`, `tony/apps/cli/{chat,main}.py`, `agents/edith/policy.yaml`, `agents/viernes/tool/tool.json`, `tests/core/guard/shipped_policy.py`, and the test asserting Viernes' declared natives.
- Builds on the uncommitted changes `phase1-conversations-doctor-policy` and `approvals-and-action-journal` (proxy journal and argument re-check, `Confirm.approval_id`, conversation commands); no spec name or requirement name collides with them.
- Out of scope: desktop UI (source cards, clarification dialog), OS sandboxing, any new permission.
