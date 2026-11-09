## 1. Tool result cap (tool-proxy)
- [x] 1.1 Write failing tests: `cap_text` boundaries (limit-1, limit, limit+1, 0 disables, marker text exact); proxy returns capped text, logs full text, leaves errors alone; `Limits` default and policy parsing with and without the key
- [x] 1.2 Add `Limits.tool_result_max_chars`, `cap_text` and use them in `ToolProxy.call`

## 2. History budget (conversation-memory)
- [x] 2.1 Write failing tests: `fit_history` under/over/equal budget, oldest dropped first, order kept, single huge message cut with `[…]`, 0 disables; config default and validation; prompt built from the fitted history
- [x] 2.2 Add `TonyConfig.history_max_chars`, `fit_history` and use it in `Conversation._prompt`

## 3. Verification
- [x] 3.1 Run the full suite and mutation testing on the diff (>95 %, abort at 3 min)
