---
name: test-design-principles
description: Use when choosing test inputs, designing test cases, selecting coverage criteria, or picking test doubles. Reference for equivalence classes, boundary analysis, decision tables, state transitions, pairwise testing, property-based testing, and the test doubles hierarchy.
---

# Test Design Principles

## Core Philosophy

Few great tests over many weak ones. See "Few Great Tests Over Many Weak Ones" below for what distinguishes a high-value test from a weak one.

## Test Design Techniques

### 1. Equivalence Class Partitioning
Divide the input domain into classes where all values behave identically. Write one representative test per class. Testing two values from the same class adds no information.

*Example:* A function accepting ages 0–120: valid class (1–120), below zero (invalid), above 120 (invalid), zero (boundary). Four tests, not hundreds.

### 2. Boundary Value Analysis
Test at the edges of equivalence classes: the boundary itself, one below, one above. Off-by-one errors live here.

*Example:* For a range check `x >= 18`: test 17 (below), 18 (boundary), 19 (above).

### 3. Decision Table Testing
When logic combines multiple conditions (A AND B AND NOT C), enumerate all meaningful combinations as a table and derive one test per row. Use for business rules with multiple boolean inputs.

| Condition A | Condition B | Expected |
|-------------|-------------|----------|
| true        | true        | result X |
| true        | false       | result Y |
| false       | true        | result Y |
| false       | false       | result Z |

### 4. State Transition Testing
For systems with explicit states (FSMs, order lifecycle, workflows):
- Test every valid transition
- Test every invalid transition (should be rejected or raise)
- Test state invariants — properties that must hold in every state

### 5. Pairwise / Combinatorial Testing
When exhaustive combination testing is infeasible, use pairwise coverage: ensure every pair of parameter values appears in at least one test. Reduces test count dramatically while catching most interaction defects.

Tools: PICT, AllPairs, hypothesis (Python), fast-check (JS/TS).

### 6. Error Guessing
Systematically probe inputs known to cause failures:
- `null` / `nil` / `undefined`
- Empty string / empty collection
- Zero, negative numbers, `MAX_INT`, `MIN_INT`
- Unicode, emoji, right-to-left text, whitespace-only
- Concurrent access, duplicate submissions
- Missing required fields, extra unexpected fields

### 7. Cause-Effect Graphing
Map causes (inputs, conditions) to effects (outputs, state changes) as a graph. Derive a minimal test set that exercises all cause-effect paths. Use when decision tables become unwieldy.

### 8. Property-Based Testing
Define properties that must hold for all inputs (e.g., "encode then decode always returns the original"). Let a framework generate inputs automatically. Use when the output space is large or an invariant is clear.

*Good candidates:* serialization round-trips, sorting invariants, mathematical identities, idempotency.

### 9. Test Coverage Criteria
Choose the criterion appropriate to risk level:

| Criterion | What it measures | When to use |
|-----------|-----------------|-------------|
| Line coverage | Lines executed | Minimum baseline only |
| Branch coverage | All true/false outcomes | Standard default |
| Path coverage | All execution paths | Often infeasible; use for critical small functions |
| MC/DC | Every condition independently affects the decision | Safety-critical (DO-178C, ISO 26262) |

Coverage is a floor, not a ceiling. 100% branch coverage with weak assertions catches nothing.

### 10. Test Oracles
How do you know if output is correct?

| Oracle type | How it works |
|-------------|-------------|
| Reference implementation | Two independent implementations agree |
| Derived properties | Property-based: invariants hold |
| Golden files | Regression: matches known-good output |
| Metamorphic relations | Changing input predictably changes output |
| Human review | Exploratory / acceptance testing |

---

## Few Great Tests Over Many Weak Ones

**High-value test:**
- Covers exactly one equivalence class or boundary
- Has a precise assertion (specific value, not just truthy/defined)
- Produces an isolated, readable failure signal
- Is deterministic and fast

**Weak test:**
- Duplicates another test's input class
- Asserts only that something didn't throw
- Is slow, flaky, or environment-dependent
- Tests implementation details rather than behavior

---

## Test Doubles Hierarchy

Prefer the lightest double that makes the test work. Heavier doubles couple tests to implementation details and slow feedback loops.

| Double | What it is | When to use |
|--------|-----------|-------------|
| **Fake** | Working simplified implementation (in-memory DB, fake HTTP server) | Default when a real dependency is too heavy |
| **Stub** | Returns hardcoded values, no behavior | When you only need a dependency to return something |
| **Mock** | Verifies interactions (was this called? with what args?) | When the interaction itself is the behavior under test |
| **Spy** | Records calls on a real object | When you want real behavior plus call verification |
| **Container / real** | Actual infrastructure | Only when the integration itself must be tested |

**Preference order:** Fakes → Mocks/Stubs → Spies → Testcontainers (last resort).

**Guidance:**
- Fakes > Mocks/Stubs: mocks and stubs couple tests to call signatures or hardcoded returns; fakes exercise real behavior
- Mocks/Stubs > Spies: state expectations directly rather than recording calls on a real object, unless you specifically need real behavior plus call verification
- Spies > Testcontainers: spies stay fast and in-process; reach for real infrastructure only as a last resort
- Use containers only in dedicated integration tests, not unit tests
- Avoid mocking types you don't own (third-party libraries) — wrap them first
