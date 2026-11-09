## Why

Two payloads reach the model without a size bound: the full text of every tool result, and up to 20 replayed history messages whatever their length. One large document or listing, or a few long replies, can multiply input tokens on every following step and turn. Bounding both with configurable, generous defaults saves tokens without changing normal-sized interactions.

## What Changes

- Successful tool results returned to the model are capped at `tool_result_max_chars` (new optional policy limit, default 20000, `0` disables), ending with an explicit truncation marker that states shown and total sizes. The complete masked result stays in the task log. Error results are never truncated.
- The replayed `<historial>` is limited to `history_max_chars` (new optional setting in `tony.yaml`, default 12000, `0` disables): oldest messages are dropped first, the newest is always kept (cut with `[…]` only if alone it exceeds the budget). The 20-message window still applies first and stored history is untouched.
- Nothing existing is removed or renamed; the shipped `policy.yaml` is unchanged.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `tool-proxy`: results sent to the model are size-capped with a marker.
- `conversation-memory`: replayed history has a character budget.

## Impact

- Code: `tony/core/guard/policy.py` (`Limits`), `tony/core/orchestrator/proxy.py`, `tony/core/config/settings.py`, `tony/core/orchestrator/conversation.py`.
- Events/API: none changed. Dependencies: none.
