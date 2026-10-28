---
name: unit-testing
description: Use when writing or reviewing unit tests. Covers isolation patterns, seam identification, test doubles in unit tests, naming conventions, and what to assert.
---

# Unit Testing

A unit test is: fast (milliseconds), no I/O, deterministic, tests one unit of behavior in isolation.

Also read `test-design-principles.md` to choose inputs systematically.

## What Counts as a Unit

A unit is the smallest piece of behavior that can be tested independently — a function, method, or small cluster of collaborating objects with a clear interface. A unit test never crosses a process boundary (no network, no filesystem, no real clock, no real DB).

## Isolation and Seams

A **seam** is a place where you can substitute behavior without modifying the code under test.

- Constructor / initializer injection
- Function parameter injection
- Module-level import (swap in test)
- Factory function / provider

**Inject test doubles at seams.** Never patch globals or use static singletons if you can avoid it. A test that requires extensive setup to isolate is signaling a design problem — the production code likely needs a seam added.

## Test Doubles in Unit Tests

Refer to the hierarchy in `test-design-principles.md`.

- Default to **fakes** or **stubs** for dependencies
- Use **mocks** only when verifying a side-effectful interaction (e.g., "an event was emitted", "a message was sent")
- Never use real I/O — inject a fake clock, fake filesystem, fake mailer, etc.
- Never spin up a container in a unit test

## Naming

Name tests as complete sentences describing behavior:

```
"returns empty list when input is empty"       ✓
"throws InvalidAge when age is negative"       ✓
"test_method_1"                                ✗
"testEdgeCase"                                 ✗
```

Group tests by the unit under test, not by test type.

## What to Assert

- Assert on **observable outputs and state**, not internal implementation
- One logical assertion per test — multiple `expect`/`assert` calls on the same result are fine; testing two different behaviors in one test is not
- Assert **specific values**, not just truthiness (see mutation-resistant test design in `mutation-testing.md`)

## Seams in Non-OO Languages

Seams exist in any language:
- **Function parameters** — pass the dependency as an argument
- **Module imports** — swap the imported module in test setup
- **Closures** — capture a fake in the closure
- **Higher-order functions** — pass behavior as a function argument

The pattern is the same: make the dependency substitutable without modifying the unit under test.
