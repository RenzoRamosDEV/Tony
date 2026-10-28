---
name: lang-java
description: Use when writing or reviewing tests in Java. Quick reference for JUnit 5, AssertJ, Mockito, and Java-specific test design gotchas.
---

# Java Testing Quick Reference

Also read `test-design-principles.md` and the relevant testing-type module (`unit-testing.md`, `integration-testing.md`, etc.).

## Recommended Stack

| Concern | Library |
|---------|---------|
| Test runner | JUnit 5 (`junit-jupiter`) |
| Assertions | AssertJ (`assertThat(...)`) |
| Mocks / stubs / spies | Mockito |
| Fakes | Hand-rolled classes implementing the interface |
| Property-based | jqwik |
| Integration / containers | Testcontainers (last resort) |
| Mutation testing | PIT (Pitest) |

## Minimal Test Structure

```java
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.assertThat;

class OrderServiceTest {

    @Test
    void returns_empty_list_when_no_orders_exist() {
        var repo = new InMemoryOrderRepository(); // fake
        var service = new OrderService(repo);

        var result = service.listOrders();

        assertThat(result).isEmpty();
    }
}
```

## Equivalence Classes and Boundary Testing

Use `@ParameterizedTest` with `@MethodSource` or `@CsvSource`:

```java
@ParameterizedTest
@CsvSource({"17, false", "18, true", "19, true", "0, false", "-1, false"})
void isAdult_returns_correct_result(int age, boolean expected) {
    assertThat(AgeChecker.isAdult(age)).isEqualTo(expected);
}
```

## Test Doubles

```java
// Stub — returns a value
UserRepository repo = Mockito.mock(UserRepository.class);
when(repo.findById(1L)).thenReturn(Optional.of(user));

// Mock — verifies interaction
verify(emailSender).send(eq("user@example.com"), any());

// Fake — preferred for complex state
class InMemoryUserRepository implements UserRepository {
    private final Map<Long, User> store = new HashMap<>();
    // ...
}
```

## Gotchas

- **Static methods:** require `MockedStatic` — a signal to reconsider design. Prefer extracting static logic behind an interface.
- **PowerMock:** avoid. It signals the code under test has untestable design (static, final, private). Refactor instead.
- **Spring context in unit tests (`@SpringBootTest`):** anti-pattern for unit tests. Instantiate collaborators directly. Use `@SpringBootTest` only for full integration tests.
- **`@MockBean`:** loads a Spring context — slow. In unit tests, inject mocks via constructor instead.
- **Mocking third-party types:** avoid mocking types you don't own (e.g., `HttpServletRequest`). Wrap them behind your own interface first.
