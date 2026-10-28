---
name: lang-php
description: Use when writing or reviewing tests in PHP. Quick reference for PHPUnit, Prophecy, Mockery, and PHP-specific gotchas around global state, static methods, and database isolation.
---

# PHP Testing Quick Reference

Also read `test-design-principles.md` and the relevant testing-type module.

## Recommended Stack

| Concern | Library |
|---------|---------|
| Test runner | PHPUnit |
| Mocks / stubs | Prophecy (bundled with PHPUnit) or Mockery |
| Fakes | Hand-rolled classes implementing the interface |
| Property-based | PHPUnit's `@dataProvider` (combinatorial); Eris for property-based |
| Mutation testing | Infection |

## Minimal Test Structure

```php
use PHPUnit\Framework\TestCase;

class OrderServiceTest extends TestCase
{
    public function test_returns_empty_list_when_no_orders_exist(): void
    {
        $repo = new InMemoryOrderRepository(); // fake
        $service = new OrderService($repo);

        $result = $service->listOrders();

        $this->assertSame([], $result);
    }
}
```

## Equivalence Classes and Boundary Testing

```php
/**
 * @dataProvider ageProvider
 */
public function test_is_adult(int $age, bool $expected): void
{
    $this->assertSame($expected, AgeChecker::isAdult($age));
}

public static function ageProvider(): array
{
    return [
        'below zero'      => [-1,  false],
        'zero'            => [0,   false],
        'below threshold' => [17,  false],
        'threshold'       => [18,  true],
        'above threshold' => [19,  true],
    ];
}
```

## Test Doubles

```php
// Prophecy stub
$repo = $this->prophesize(OrderRepository::class);
$repo->findById(1)->willReturn($order);
$service = new OrderService($repo->reveal());

// Prophecy mock — verify interaction
$repo->save($order)->shouldHaveBeenCalledOnce();

// Fake — preferred for stateful deps
class InMemoryOrderRepository implements OrderRepository
{
    private array $store = [];

    public function findById(int $id): ?Order
    {
        return $this->store[$id] ?? null;
    }

    public function save(Order $order): void
    {
        $this->store[$order->getId()] = $order;
    }
}
```

## Gotchas

- **Global state and static methods:** pervasive in legacy PHP code (`$_SESSION`, `$_GET`, static service locators). Isolate behind interfaces before testing. If you must test code with static calls, use `Mockery::mock('alias:ClassName')` as a last resort — but prefer refactoring.
- **`setUp` / `tearDown` and global/static state:** any static or global state modified during a test must be explicitly reset in `tearDown`. Failure to do so causes test order dependencies.
- **Database tests:** use transactions rolled back after each test (`$this->beginTransaction()` in `setUp`, `$this->rollback()` in `tearDown`), or re-seed fixtures per test. Never leave test data in a shared database.
- **`$this->createMock()` vs Prophecy:** PHPUnit's built-in `createMock()` is lower-level. Prophecy is more expressive for complex expectations. Mockery offers fluent syntax and is preferred for third-party-heavy codebases.
- **Testing `final` classes:** PHPUnit cannot mock `final` classes by default. Either remove `final`, extract an interface, or use `dg/bypass-finals` (last resort).
