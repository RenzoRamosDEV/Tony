# Tasks

Order: tests first (red), then code (green), then refactor, per group. Prerequisite and verification commands use the project test runner (`pytest`) on the touched test files only; mutation testing only on the diff.

## 0. Prerequisites

- [x] 0.1 Confirm `tony/core/memory/actions.py`, `tests/apps/test_cli_actions.py` and the `journal` field of `RunDeps` exist in the working tree (the three uncommitted changes are present) and `pytest tests/core/memory tests/core/orchestrator tests/apps -q` is green before touching anything; if not, stop and report.

## 1. Task origin and resume link (log and events)

- [x] 1.1 Write failing tests: `log_events.task_started` and `core_events.task_started` add `origin` / `resumed_from` only when given; existing shapes unchanged; `send_message` with `origin: "routine"` is rejected (tests/core/events, tests/core/orchestrator/test_commands.py)
- [x] 1.2 Add `TaskOrigin`, the optional keys, and `run_task(..., origin=None, resumed_from=None)` wiring; add optional `origin?` to the desktop `task_started` TS type; verify 1.1 passes and the existing event/log tests still pass

## 2. Undo store and proxy snapshots

- [x] 2.1 Write failing tests for `UndoStore` (tests/core/memory/test_undo.py) using `tmp_path`: stores previous bytes + sidecar for an existing small file; skips missing, 1 MB + 1 byte (boundary 1 MB stored), non-UTF-8; ignores other tools; `written_digest` is sha256 of UTF-8 content; `load` rejects ids that are not uuids
- [x] 2.2 Implement `tony/core/memory/undo.py`; verify 2.1 passes
- [x] 2.3 Write failing proxy tests with a fake snapshot port and fake caller (tests/core/orchestrator/test_proxy.py): `keep` runs after `prepared` and before `dispatched`; `succeeded` row detail is `sha256=<hex>` for `filesystem.write_file`; other tools untouched; a raising `keep` still executes the call and publishes one `error`; denied calls take no snapshot
- [x] 2.4 Add the `ActionSnapshots` port and `ToolProxy(snapshots=...)`, `RunDeps.snapshots`; verify 2.3 passes
- [x] 2.5 Write failing wiring test (tests/apps/test_journal_wiring.py style): `tony run` with a fake engine writing over an existing file leaves `memory/undo/<call_id>`; then wire `UndoStore` into `running_journal` users in main.py, `run_chat` and `CoreRuntime`; verify it passes

## 3. Recovery listing and resume

- [x] 3.1 Write failing tests for `ActionJournal.for_task` (ordering, state filter) in tests/core/memory
- [x] 3.2 Implement `for_task`; verify 3.1 passes
- [x] 3.3 Write failing tests for `scan_tasks` and `resume_request` (tests/core/recovery/test_tasks.py) with hand-written jsonl logs and a fake clock: `cancelled`/`timeout` listed, `ok`/`error` not, no-end-event listed only past 900 s (boundary at 900/899 s), malformed lines skipped, logs without `task_started` ignored, resumed originals hidden, note text lists succeeded actions, caps at 20, keeps original `contexto`
- [x] 3.4 Implement `tony/core/recovery/tasks.py`; verify 3.3 passes
- [x] 3.5 Write failing CLI tests (tests/apps/test_cli_recover.py, `CliRunner`, fake engine): `recover list` output incl. `undoable` / `not undoable` labels and `no tasks to recover`; `recover resume` starts a new task id with `resumed_from` and the note in `contexto`; unknown id, non-hex id and non-recoverable task give the usage error; the guard still asks confirmations
- [x] 3.6 Implement `tony/apps/cli/recover_commands.py` (`list`, `resume`) and register it in `create_app`; verify 3.5 passes

## 4. Undo

- [x] 4.1 Write failing tests for `runner.run_guarded_call` (tests/core/orchestrator/test_runner.py): goes through the guard (deny blocks, confirmation asked), writes a task log and a journal row, returns the tool reply
- [x] 4.2 Implement `run_guarded_call`; verify 4.1 passes
- [x] 4.3 Write failing tests for undo checks and CLI (tests/core/recovery/test_undo.py, tests/apps/test_cli_recover.py): restores when current sha256 equals the recorded one; `file changed since the action` otherwise (also when the file is missing) with nothing written; `not undoable` for other tools; unknown call, not-`succeeded` and missing pre-image refusals; denied confirmation writes nothing; undo creates its own pre-image
- [x] 4.4 Implement `tony/core/recovery/undo.py` and the `recover undo` command; verify 4.3 passes

## 5. Routine storage, occurrences and CLI

- [x] 5.1 Write failing tests for `occurrences` (tests/core/automation/test_occurrences.py) with fixed datetimes: weekday mask, 12 h lateness boundary (12:00:00 runs, +1 s skipped), `active_since` floor, id from configured local date/time, Europe/Madrid 2026-03-29 02:30 gap and 2026-10-25 02:30 repeat each yield one id, negative-offset zone, date change across midnight
- [x] 5.2 Implement `tony/core/automation/occurrences.py`; verify 5.1 passes
- [x] 5.3 Write failing tests for `RoutineStore` (tests/core/automation/test_store.py): add/list/remove/enable/disable, validation (time, weekday names, tz, empty prompt), `INSERT OR IGNORE` uniqueness, claim race returns one winner, inbox LEFT JOIN keeps removed routine runs, enable resets `active_since`
- [x] 5.4 Implement `tony/core/automation/store.py` and `local_zone_name`; verify 5.3 passes
- [x] 5.5 Write failing CLI tests (tests/apps/test_cli_routines.py): `add` with defaults and options, `list`, `remove`, `enable`, `disable`, `inbox --limit`, usage errors for invalid input and unknown ids
- [x] 5.6 Implement `tony/apps/cli/routines_commands.py` and register it; verify 5.5 passes

## 6. Scheduler and hosts

- [x] 6.1 Write failing scheduler tests (tests/core/automation/test_scheduler.py) with fake clock, fake `run`, fake `unlocked`, no sleeping: due occurrence runs once across repeated ticks; second scheduler on the same DB does not rerun; late > 12 h stored `skipped`; locked stays `queued` and runs after unlock; queued past 12 h becomes `skipped`; `ok`/`error` records with masked result capped at 2000 chars; stale claim (> 600 s) marked `error` `interrupted`; a raising `run` or tick publishes an `error` and the next tick still works; scheduler never calls a PIN prompt
- [x] 6.2 Implement `tony/core/automation/scheduler.py` and `launcher.py` (`run_task(..., origin="routine")`); verify 6.1 passes
- [x] 6.3 Write failing host tests: `run_chat` (tests/apps/test_cli_chat.py) starts the scheduler, prints nothing for routine results, stops it on `/salir`; `CoreRuntime` (tests/core/orchestrator/test_runtime.py) starts it after a successful start, publishes `error` on tick failure and cancels it on shutdown; a routine task log has `origin: "routine"`
- [x] 6.4 Wire the scheduler into `run_chat` and `CoreRuntime` (locked check from `EdithSession.unlocked`, quiet publisher in chat); verify 6.3 passes
- [x] 6.5 Add an end-to-end test: fake engine + guard policy requiring confirmation + no answer -> action denied after the confirmation timeout (fake monotonic), run recorded; verify it passes

## 7. Finish

- [x] 7.1 Refactor pass on touched code (SRP, naming) keeping tests green; run mutation testing only on the diff and justify surviving mutants (> 95% target, abort at 3 minutes)
- [ ] 7.2 Run `pytest -q`, linters configured in the project, and `openspec validate recovery-and-routines`; verify all pass and no existing test regressed
- [x] 7.3 Document `tony recover` and `tony routines` (usage, "routines run only while Tony runs", `memory/undo/` and `memory/routines.sqlite`) in the project's user docs; verify each documented command runs as written

## Workflow follow-up

- Archive the change after review; follow-up change for `memory/undo/` retention.
