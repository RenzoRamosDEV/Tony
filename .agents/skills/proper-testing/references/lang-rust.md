---
name: lang-rust
description: Use when writing or reviewing tests in Rust. Quick reference for the built-in test framework, rstest, proptest, mockall, and Rust-specific gotchas around ownership, async tests, and test isolation.
---

# Rust Testing Quick Reference

Also read `test-design-principles.md` and the relevant testing-type module (`unit-testing.md`, `integration-testing.md`, etc.).

## Recommended Stack

| Concern | Library |
|---------|---------|
| Test runner | Built-in (`cargo test`) |
| Assertions | Built-in `assert_eq!`, `assert!`, plus `pretty_assertions` for readable diffs |
| Parameterized / data-driven | rstest (`#[rstest]` + `#[case]`) |
| Mocks / stubs | mockall |
| Fakes | Hand-rolled structs implementing the trait (preferred) |
| Property-based | proptest or quickcheck |
| Mutation testing | cargo-mutants |

## Minimal Test Structure

```rust
// Unit tests live in the same file as the code under test
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn returns_empty_vec_when_no_orders_exist() {
        let repo = InMemoryOrderRepository::new(); // fake
        let service = OrderService::new(repo);

        let result = service.list_orders();

        assert!(result.is_empty());
    }
}
```

Integration tests live in `tests/` at the crate root — they only access public API.

## Equivalence Classes and Boundary Testing

Use `rstest` for parameterized tests:

```rust
use rstest::rstest;

#[rstest]
#[case(-1, false)]
#[case(0,  false)]
#[case(17, false)]
#[case(18, true)]
#[case(19, true)]
fn test_is_adult(#[case] age: i32, #[case] expected: bool) {
    assert_eq!(is_adult(age), expected);
}
```

## Property-Based Testing (proptest)

```rust
use proptest::prelude::*;

proptest! {
    #[test]
    fn encode_decode_roundtrip(s in ".*") {
        let encoded = encode(&s);
        prop_assert_eq!(decode(&encoded), s);
    }
}
```

## Test Doubles

Rust's ownership model makes mocking harder than in GC languages. Prefer fakes.

```rust
// Fake via trait — strongly preferred
struct InMemoryOrderRepository {
    store: HashMap<u64, Order>,
}

impl OrderRepository for InMemoryOrderRepository {
    fn find_by_id(&self, id: u64) -> Option<&Order> {
        self.store.get(&id)
    }
    fn save(&mut self, order: Order) {
        self.store.insert(order.id, order);
    }
}

// Mock with mockall (when interaction verification is needed)
use mockall::mock;

mock! {
    pub EmailSender {}
    impl EmailSender for MockEmailSender {
        fn send(&self, to: &str, body: &str);
    }
}

// In test:
let mut mock = MockEmailSender::new();
mock.expect_send()
    .with(eq("user@example.com"), always())
    .times(1)
    .return_const(());
```

## Gotchas

- **`#[cfg(test)]` module:** unit tests live inside the module they test (not a separate file). This gives access to private functions — use it deliberately, not as a shortcut to skip designing proper interfaces.
- **Ownership in fakes:** if a trait method takes `self` by value, fakes become awkward. Prefer `&self` / `&mut self` in trait definitions to keep fakes implementable.
- **Async tests:** use `#[tokio::test]` (or `#[async_std::test]`) — `#[test]` does not support `async fn`. Prefer synchronous fakes where possible to keep unit tests runtime-free.
- **`unwrap()` in tests:** acceptable in tests for brevity, but use descriptive `expect("reason")` for failures that need context. Avoid `unwrap()` in shared test helpers.
- **Integration test visibility:** files in `tests/` only see the crate's public API. If you need to test internal behavior, use `#[cfg(test)]` unit tests inside the module instead.
- **`cargo test` parallelism:** tests run in parallel by default. Tests that share global state (static variables, environment variables) will race. Use `serial_test` crate or avoid shared state entirely.
