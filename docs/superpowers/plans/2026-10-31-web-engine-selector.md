# Web engine selector implementation plan

**Goal:** Select the speaking agent's engine in the existing web interface.
**Architecture:** GET/PATCH /api/engines lists configured profiles and switches the front through its existing factory. The hub serializes changes, opens a fresh conversation and atomically persists agent.md after successful opening. On failure it restores the previous engine and conversation. React shows the selector in the header.
**Tech Stack:** FastAPI, React, TypeScript, pytest, Vitest.

## Constraints

No git operations or changes to engine implementations. Spanish visible text. Keep old conversation history. Reject switching during turns, tasks or microphone capture. Use configured profiles only.

## Steps

- [x] Observe failing backend tests for inventory, switching, persistence, unknown profile, busy state and rollback.
- [x] Implement API and hub switching with the runtime factory and atomic editor.
- [x] Observe failing frontend tests for options, selection, disabled state and errors; implement and mount the selector.
- [x] Run backend/frontend tests, typecheck, build and Ruff.

## Verification

Backend engine/hub tests: 57 passed. Runtime bootstrap tests: 9 passed. Frontend suite: 317 passed; after final styling and mounted-selector assertion, 42 focused tests passed again. TypeScript and production build passed. Ruff: all checks passed, 447 files already formatted. The existing TestClient-based settings regression stalled in this environment and was interrupted; the new API tests use ASGITransport and passed. The local configuration now declares the Codex profile; LiteLLM remains available for configured provider/model profiles. No git operations or engine implementation edits.
