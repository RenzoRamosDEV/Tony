## Why

Tony loses every conversation when the app restarts, offers no way to diagnose a broken installation, and gives the user no way to see or undo what Edith has been told to allow always. These three gaps (resume/manage conversations, an installation doctor, a permission inspector) are small, local, and safe to deliver as one slice without touching Edith's safety model.

## What Changes

- `HistoryStore` can list, search and delete conversations; core commands `ListConversations`, `ResumeConversation{id}`, `DeleteConversation{id}` and an event `conversations{items}` expose them. Resuming only switches the id used for new messages; nothing is replayed, no permission or approval is restored.
- CLI: `tony chat --resume [ID]` and `tony conversations list|search TEXT|delete ID`.
- New `tony doctor` command and `tony/core/diagnostics/` module: local, non-executing checks (definitions load, MCP commands/URLs, `${NAME}` placeholders resolve, optional voice/music dependencies) printed as `check | status | hint`; exit 1 on any `fail`.
- New `tony policy` subcommands: `explain TOOL [--args JSON]`, `grants`, `revoke TOOL`, `simulate FILE`, built on the real `evaluate` and the existing atomic policy rewrite.
- No change to `evaluate`, first-match semantics, `agents/edith/policy.yaml`, existing commands, events or config keys. New event/command types are additive.

## Capabilities

### New Capabilities
- `diagnostics`: installation doctor checks, statuses and CLI contract.
- `policy-management`: `tony policy` explain/grants/revoke/simulate contract.

### Modified Capabilities
- `conversation-memory`: list/search/delete/resume conversations in the history store.
- `chat-cli`: `tony chat --resume` and `tony conversations` subcommands.
- `core-events`: `conversations` event and the three new core commands.

## Impact

- Code: `tony/core/memory/history.py`, `tony/core/orchestrator/{commands,conversation,runtime}.py`, `tony/core/events/core_events.py`, `tony/apps/cli/{main,chat}.py`, `tony/core/guard/allow_always.py` (revoke added beside insert), new `tony/core/diagnostics/`, new `tony/core/guard/` simulate/explain helpers, `tony/core/config/placeholders.py` (public placeholder-name scan).
- Tests: new unit tests per module plus CLI tests; shipped policy unchanged.
- Out of scope: desktop conversation picker and diagnostics panel, optional connection probes, OS sandboxing.
- Safety invariant: nothing here grants a permission, bypasses a confirmation or the PIN, or lets model-written text change policy; `revoke` and `simulate` are user-run CLI commands only and are not exposed as model tools or core commands.
