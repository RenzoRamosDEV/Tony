---
name: mutation-testing
description: Use when applying mutation testing, measuring test suite strength, or writing tests that would catch defects in logic mutations. Covers what mutation testing is, when to apply it, and how to write mutation-resistant tests.
---

# Mutation Testing

## What It Is

Mutation testing measures test suite **strength**, not coverage.

**Tool:** See your language file (`lang-java.md`, `lang-python.md`, etc.) for the recommended mutation testing tool (Pitest, Stryker, mutmut, Stryker4s, Stryker.NET, Infection, cargo-mutants).

A mutation testing tool makes small automated changes (mutations) to production code:
- Flip `>` to `>=`
- Remove a `return` statement
- Negate a condition (`if x` → `if !x`)
- Replace a constant (`42` → `0`)

Then it runs the test suite. If a mutation **survives** (no test fails), the suite has a gap — the code changed but nothing caught it.

**Coverage tells you what code was executed. Mutation testing tells you whether your assertions would catch a defect.**

## When to Apply

Apply mutation testing to:
- Critical paths: business logic, security checks, financial calculations, safety-critical code
- After adding a new feature — verify the tests actually validate the behavior
- When coverage is high but confidence is low

Do NOT apply to every file. Focus on high-risk modules. Mutation testing is slow — run it on a subset, not the whole codebase.

Prerequisite: an existing test suite. Mutation testing reveals gaps in existing tests; it doesn't replace writing tests from scratch.

## Writing Mutation-Resistant Tests

### Assert on specific values, not just truthiness

```
# Weak — survives many mutations
assert result is not None
assert is_valid == True
assert list is not empty

# Strong — catches boundary and logic mutations
assert result == 42
assert error_code == "INVALID_INPUT"
assert len(items) == 3
```

### Avoid over-mocking

Mocks that verify call counts/args can miss logic mutations inside the unit under test. If you mock away the behavior, mutations to that behavior survive undetected.

Prefer fakes that exercise real logic paths.

### Single-purpose assertions

A test with one precise assertion kills one class of mutants clearly. A test that asserts many things in sequence may pass even when one assertion's corresponding logic is mutated (depending on exception handling and order).

### Cover all branches explicitly

Mutation tools flip every condition. Ensure both the true and false branch of every condition have a test that would fail if the branch were mutated.

Use the decision table technique (see `test-design-principles.md`) to systematically generate this coverage.

### Use boundary values

Mutations often target comparison operators (`>` vs `>=`). Tests at the boundary (the exact threshold, one below, one above) will catch these. See boundary value analysis in `test-design-principles.md`.

## Interpreting Survival Reports

A surviving mutant is not always a bug:
- **Dead code** — the mutated code is unreachable; delete it
- **Equivalent mutation** — the mutation produces semantically identical behavior (e.g., `i++` vs `++i` in some contexts)
- **Real gap** — the mutation represents a defect your tests don't catch; add a test

Triage each survivor: is the mutated code reachable? Is the behavior observable from the outside? Add a test only if the surviving mutant represents a real gap.
