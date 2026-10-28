---
name: integration-testing
description: Use when writing or reviewing integration tests. Covers when integration tests are warranted vs contract tests, seam identification across component boundaries, test doubles for I/O, and test isolation.
---

# Integration Testing

An integration test verifies that multiple components work correctly across a real boundary (DB, HTTP, filesystem, message queue).

Also read `test-design-principles.md` for input design and doubles hierarchy.

## When Integration Tests Are Warranted

- The contract between two components is the risk — not their internals
- A fake would require so much logic it becomes its own maintenance burden
- You're verifying serialization, query correctness, or wire format

## When to Use Contract Testing Instead

Consumer-driven contract tests (e.g., Pact) are lighter than full integration tests.

Prefer contract tests when:
- Testing API compatibility between services
- The integration point is a network boundary owned by another team
- You want fast feedback without spinning up real infrastructure

## Test Doubles in Integration Tests

| Dependency | Preferred double | Use real only when |
|-----------|-----------------|-------------------|
| SQL database | In-memory / embedded (H2, SQLite) | Query behavior differs from embedded |
| HTTP service | In-process fake server (WireMock, nock, httpretty) | Wire format must be validated end-to-end |
| Message queue | In-memory fake | Message ordering/durability must be tested |
| Filesystem | Temp directory | OS-specific behavior must be tested |
| Container (Docker) | Last resort | Embedded variant doesn't cover needed behavior |

**Never use production infrastructure in tests.**

## Seam Identification

Draw the component boundary: what crosses it? (data format, protocol, timing, error codes)

- Test **at** the boundary — verify the contract
- Do **not** test through it — avoid asserting on the internals of the dependency
- If the dependency's behavior changes, only the integration test should break, not unit tests

## Isolation

- Each test must set up and tear down its own data
- Tests must be runnable in any order — no shared mutable state between tests
- Use transactions rolled back after each test, or re-seed fixtures per test
