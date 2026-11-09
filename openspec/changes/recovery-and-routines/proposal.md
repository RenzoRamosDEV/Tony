## Why

A task that is cancelled, times out or dies mid-way leaves partial side effects, and today the user can neither see what already happened nor continue safely or revert a file write. Tony also only acts when asked: recurring jobs ("every morning, check X") need a scheduler that runs under the same guard as any other task.

## What Changes

- **Recovery** (builds on the action journal of `approvals-and-action-journal`): `tony recover list`, `tony recover resume TASK_ID`, `tony recover undo CALL_ID`.
- `recover list` shows worker tasks whose log ends `cancelled`, `timeout` or without `task_finished`, with their `succeeded` actions and an `undoable` / `not undoable` label per action.
- `recover resume` submits the original request again as a NEW task (new task id, normal guard and confirmations) whose `contexto` starts with a note listing the already `succeeded` actions and saying they must not be repeated.
- Before `filesystem.write_file` runs, the proxy stores the previous content (file exists, at most 1 MB, valid UTF-8) under `memory/undo/<call_id>` and records the sha256 of the written content in the journal `detail`.
- `recover undo` restores that content through a NEW guarded `filesystem.write_file` call, only when the file's current sha256 equals the recorded one; otherwise it refuses with `file changed since the action`. Calendar compensation is out of scope.
- **Routines**: new module `tony/core/automation/`, SQLite tables `routines` and `routine_runs`, a scheduler that checks every 30 s while `tony chat` or the desktop runtime runs.
- A due occurrence runs once as a worker task with origin `routine`; a run more than 12 h late is stored `skipped`; runs wait `queued` while the guard session is locked; confirmations are asked normally and denied by the existing timeout when nobody answers (scheduling never authorises anything).
- CLI `tony routines add|list|remove|enable|disable|inbox`.
- Additive log and core-event fields `origin` and `resumed_from` on `task_started`; no existing field or origin value changes.

## Capabilities

### New Capabilities
- `task-recovery`: listing unfinished tasks, resuming them as new tasks, and undoing file writes.
- `scheduled-routines`: routine definitions, the occurrence scheduler, run records and the routines CLI.

### Modified Capabilities
- `tool-proxy`: pre-image snapshot and written-content hash around `filesystem.write_file`.
- `task-log`: `task_started` may carry `origin` and `resumed_from`.
- `core-events`: `task_started` may carry `origin`.
- `chat-cli`: `tony chat` hosts the scheduler.
- `desktop-app`: the core runtime hosts the scheduler.

## Impact

- Code: `tony/core/memory/undo.py` (new) and `actions.py` (per-task query), `tony/core/recovery/` (new), `tony/core/automation/` (new), `proxy.py`, `ports.py`, `runner.py` (`run_task` keyword args, single guarded tool call helper), `runtime.py`, `chat.py`, `main.py` plus two new CLI modules, `core_events.py`, `log_events.py`, desktop `types.ts` (optional field).
- Data: `memory/undo/`, `memory/routines.sqlite`; no migration of existing data.
- Dependencies: none new (stdlib `zoneinfo`, `sqlite3`, `hashlib`); needs system tzdata.
- Prerequisite: the working tree changes of `phase1-conversations-doctor-policy`, `approvals-and-action-journal` and `clarification-and-evidence` are uncommitted; this change edits the same files and must be applied on top of them.
