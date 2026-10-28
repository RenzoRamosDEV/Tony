---
name: lang-scala
description: Use when writing or reviewing tests in Scala. Quick reference for ScalaTest, MUnit, ScalaCheck, and Scala-specific gotchas around implicits and Future-based code.
---

# Scala Testing Quick Reference

Also read `test-design-principles.md` and the relevant testing-type module.

## Recommended Stack

| Concern | Library |
|---------|---------|
| Test runner | ScalaTest (FunSpec / AnyFlatSpec) or MUnit |
| Property-based | ScalaCheck (integrated in ScalaTest via `ScalaCheckPropertyChecks`) |
| Mocks | ScalaMock or Mockito-Scala |
| Fakes | Trait implementations (idiomatic — preferred) |
| Mutation testing | Stryker4s |

## Minimal Test Structure (MUnit)

```scala
class OrderServiceSuite extends munit.FunSuite {

  test("returns empty list when no orders exist") {
    val repo = new InMemoryOrderRepository // fake via trait
    val service = new OrderService(repo)

    val result = service.listOrders()

    assertEquals(result, List.empty)
  }
}
```

## Equivalence Classes and Boundary Testing (ScalaCheck)

```scala
import org.scalacheck.Prop.forAll
import org.scalacheck.Gen

property("encode then decode returns original") {
  forAll(Gen.alphaStr) { s =>
    Codec.decode(Codec.encode(s)) == s
  }
}
```

## Test Doubles

```scala
// Fake via trait — preferred
class InMemoryUserRepo extends UserRepository {
  private var users: Map[Long, User] = Map.empty
  def findById(id: Long): Option[User] = users.get(id)
  def save(user: User): Unit = users = users + (user.id -> user)
}

// Mock with ScalaMock
val repo = mock[UserRepository]
(repo.findById _).expects(1L).returning(Some(user))
```

## Gotchas

- **Implicits masking dependencies:** if a dependency is passed implicitly, it may be invisible in tests. Make implicits explicit in test scope — pass them as explicit parameters or declare them in the test scope with a fake implementation.
- **`Future`-based code in unit tests:** avoid `Await.result` in unit tests — it makes tests slow and hides timing issues. Prefer synchronous fakes: a fake that returns `Future.successful(value)` keeps tests fast without concurrency.
- **`eventually` in unit tests:** `eventually` polls until a condition is true — appropriate for integration tests, not unit tests. If you need `eventually` in a unit test, the code under test has a concurrency design issue.
- **Mocking traits with `val` members:** ScalaMock can mock traits, but traits with `val` members require careful setup. Prefer hand-rolled fakes for complex interfaces.
