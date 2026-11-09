# Proposal

## Why

A confirmation today approves a tool name plus a 200-character preview. Nothing ties the "yes" to the exact arguments that later execute, nothing shows the user the authoritative content (full email body, file content), an answer has no expiry and survives a policy edit, and there is no durable record of which side-effecting calls were started or finished. A crash or timeout mid-call leaves no trace of whether a message was sent or a file written.

## What Changes

- Typed action previews: masked, capped, per-tool fields (email recipients and body, file path and content, calendar event fields) shown in the confirmation request.
- Each confirmation request becomes an approval carrying `approval_id`, `args_digest`, `policy_version`, `expires_at` and `preview` as additive optional event fields.
- The broker accepts an answer only for the pending, unexpired approval; before executing, the call is cancelled if its arguments changed, and re-evaluated from scratch if the policy changed. An answer without `approval_id` stays valid when one approval is pending.
- Optional `approval_id` on the `confirm` command.
- New SQLite action journal (`prepared`, `dispatched`, `succeeded`, `failed`, `outcome_unknown`) written by the tool proxy; stale `dispatched` rows become `outcome_unknown` at startup; calls are never replayed.
- CLI: `tony actions list [--state STATE] [--limit N]` and `tony actions show CALL_ID`.
- Safety invariant: nothing here grants a permission, bypasses a confirmation or the PIN, or lets model text change policy. Existing commands, events, config keys and the shipped policy are unchanged; new fields are optional.

## Capabilities

### New Capabilities
- `action-journal`: durable per-call state record of guarded tool executions, recovery of interrupted calls and the `tony actions` inspection commands.

### Modified Capabilities
- `guard-confirmation`: typed previews, approval binding (id, digest, policy version, expiry) and answer acceptance rules.
- `guard-audit`: confirmed audit lines record the approval id.
- `core-events`: `needs_confirmation` approval fields and optional `approval_id` on `confirm`.
- `tool-proxy`: argument re-check before dispatch and journal writes around execution.

## Impact

- Code: `tony/core/guard/` (new `previews.py`, `edith.py`, `broker.py`, `confirm.py`, `audit.py`), `tony/core/config/reload.py` and `tony/core/guard/policy.py` (policy version), `tony/core/events/core_events.py`, `tony/core/orchestrator/{proxy,commands,runner,runtime}.py`, new `tony/core/memory/actions.py`, `tony/apps/cli/main.py`, desktop bridge TypeScript types (optional field only).
- Data: new file `memory/actions.sqlite`; no migration of existing files.
- Not in scope: desktop UI changes, reconciliation of `outcome_unknown` against connectors, OS sandboxing.
