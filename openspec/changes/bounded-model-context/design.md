## Context

Observed: `Limits` (policy.py) holds timeouts, retries, alert and step limits with `extra="forbid"`; `ToolProxy.call` masks the reply text and logs it, then returns it; `TonyConfig` holds front/worker/guard, reply mode, models, voice, desktop; `Conversation._prompt` joins the messages returned by `HistoryStore.recent(limit=20)`.

## Decisions

1. **Cap in the proxy, after masking.** `ToolProxy.call` logs the full masked reply first, then returns a copy cut by a pure `cap_text(text, limit)` helper (no cut when `limit` is 0 or text fits). Errors skip the helper. The limit is read from the supervisor's `limits` (new `Limits.tool_result_max_chars = 20000`), so it reloads with the policy and the shipped `policy.yaml` needs no edit.
2. **History trimming as a pure function.** `fit_history(messages, max_chars)` keeps the longest newest suffix whose summed `content` length fits; if even the newest alone exceeds it, it is cut to the budget minus the marker length and ends with `[…]`. Applied in `Conversation._prompt` before formatting. The budget is `TonyConfig.history_max_chars: int = 12000` (≥ 0 validated).
3. **Counting characters, not tokens.** Characters are deterministic and need no tokenizer; ~4 characters per token makes the defaults about 5000 and 3000 tokens.

## Risks / Trade-offs

- A truncated result may hide a decisive detail → generous default, explicit marker with total size, full text in the log, `0` disables.
- Dropping old turns may lose context → default 12000 keeps well over a typical 20-message window; `0` restores the previous behavior.
