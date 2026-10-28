---
name: lang-dotnet
description: Use when writing or reviewing tests in .NET / C#. Quick reference for xUnit, FluentAssertions, Moq, NSubstitute, and .NET-specific gotchas around async tests and HttpClient.
---

# .NET / C# Testing Quick Reference

Also read `test-design-principles.md` and the relevant testing-type module.

## Recommended Stack

| Concern | Library |
|---------|---------|
| Test runner | xUnit |
| Assertions | FluentAssertions (`result.Should().Be(...)`) |
| Mocks / stubs | NSubstitute (concise) or Moq (explicit verification) |
| Fakes | Hand-rolled classes implementing the interface |
| Property-based | FsCheck or CsCheck |
| Mutation testing | Stryker.NET |

## Minimal Test Structure

```csharp
public class OrderServiceTests
{
    [Fact]
    public void ListOrders_ReturnsEmpty_WhenNoOrdersExist()
    {
        var repo = new InMemoryOrderRepository(); // fake
        var service = new OrderService(repo);

        var result = service.ListOrders();

        result.Should().BeEmpty();
    }
}
```

## Equivalence Classes and Boundary Testing

```csharp
[Theory]
[InlineData(-1, false)]
[InlineData(0,  false)]
[InlineData(17, false)]
[InlineData(18, true)]
[InlineData(19, true)]
public void IsAdult_ReturnsExpected(int age, bool expected)
{
    AgeChecker.IsAdult(age).Should().Be(expected);
}
```

For complex inputs, use `[MemberData]` pointing to a static `IEnumerable<object[]>` property.

## Test Doubles

```csharp
// NSubstitute stub
var repo = Substitute.For<IOrderRepository>();
repo.FindById(1).Returns(order);

// NSubstitute mock — verify interaction
repo.Received(1).Save(Arg.Is<Order>(o => o.Id == 1));

// Fake — preferred for stateful deps
public class InMemoryOrderRepository : IOrderRepository
{
    private readonly Dictionary<int, Order> _store = new();
    public Order? FindById(int id) => _store.GetValueOrDefault(id);
    public void Save(Order order) => _store[order.Id] = order;
}
```

## Gotchas

- **`async void` test methods:** silently ignored by most runners — the test appears to pass without executing. Always use `async Task`:
  ```csharp
  [Fact]
  public async Task DoSomethingAsync_Works() // ✓
  ```
- **`HttpClient` faking:** `HttpClient` is sealed and hard to mock directly. Inject via `IHttpClientFactory`, or use a custom `HttpMessageHandler`:
  ```csharp
  var handler = new FakeHttpMessageHandler(response);
  var client = new HttpClient(handler);
  ```
- **`DateTime.Now` / `DateTimeOffset.Now`:** inject an `IDateTimeProvider` abstraction instead of calling static methods directly — enables deterministic unit tests.
- **Mocking `sealed` classes:** not supported by Moq/NSubstitute without workarounds. Wrap behind an interface instead.
