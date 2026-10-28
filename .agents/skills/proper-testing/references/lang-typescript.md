---
name: lang-typescript
description: Use when writing or reviewing tests in TypeScript or JavaScript. Quick reference for Vitest, Jest, fast-check, and gotchas around ESM interop, type assertions, and module mocking.
---

# TypeScript / JavaScript Testing Quick Reference

Also read `test-design-principles.md` and the relevant testing-type module.

## Recommended Stack

| Concern | Library |
|---------|---------|
| Test runner | Vitest (preferred for modern projects) or Jest |
| Assertions | Built-in `expect` from Vitest/Jest |
| Mocks / stubs / spies | `vi.fn()` / `jest.fn()`, `vi.spyOn()` |
| Fakes | Hand-rolled objects implementing the TypeScript interface |
| Property-based | fast-check |
| Mutation testing | Stryker |

## Minimal Test Structure

```typescript
// order-service.test.ts
import { describe, it, expect } from 'vitest';
import { OrderService } from './order-service';
import { InMemoryOrderRepository } from '../test/fakes';

describe('OrderService', () => {
  it('returns empty list when no orders exist', () => {
    const repo = new InMemoryOrderRepository(); // fake
    const service = new OrderService(repo);

    const result = service.listOrders();

    expect(result).toEqual([]);
  });
});
```

## Equivalence Classes and Boundary Testing

```typescript
it.each([
  [-1, false],
  [0,  false],
  [17, false],
  [18, true],
  [19, true],
])('isAdult(%i) returns %s', (age, expected) => {
  expect(isAdult(age)).toBe(expected);
});
```

## Property-Based Testing (fast-check)

```typescript
import fc from 'fast-check';

it('encode then decode returns original', () => {
  fc.assert(
    fc.property(fc.string(), (s) => {
      expect(decode(encode(s))).toBe(s);
    })
  );
});
```

## Test Doubles

```typescript
// Stub
const repo = { findById: vi.fn().mockResolvedValue(user) };

// Spy
const spy = vi.spyOn(emailService, 'send');
// ... run code ...
expect(spy).toHaveBeenCalledWith('user@example.com', expect.any(String));

// Fake — preferred for stateful deps
class InMemoryOrderRepository implements OrderRepository {
  private store = new Map<number, Order>();
  findById(id: number) { return this.store.get(id) ?? null; }
  save(order: Order) { this.store.set(order.id, order); }
}
```

## Gotchas

- **ESM interop with Jest:** Jest has historically struggled with ES modules. Use Vitest for new projects — it handles ESM natively without configuration workarounds.
- **Auto-mocking modules (`vi.mock()` / `jest.mock()`):** auto-mocking replaces every export with a stub. This hides type errors and couples tests to module structure. Prefer hand-rolled fakes implementing the TypeScript interface.
- **Type assertions in test setup (`as unknown as T`):** these hide real type errors. Keep `as` casts in test code to a minimum — if you need them, the fake or the interface has a mismatch worth fixing.
- **`any` in test setup:** avoid. TypeScript's type checking is one of the best free test oracles you have — don't disable it in tests.
- **Mocking timers:** use `vi.useFakeTimers()` / `jest.useFakeTimers()` rather than real `setTimeout`. Always restore with `vi.useRealTimers()` in `afterEach`.
