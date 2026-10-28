---
name: lang-python
description: Use when writing or reviewing tests in Python. Quick reference for pytest, unittest.mock, Hypothesis, and Python-specific gotchas around patching and fixture scope.
---

# Python Testing Quick Reference

Also read `test-design-principles.md` and the relevant testing-type module.

## Recommended Stack

| Concern | Library |
|---------|---------|
| Test runner | pytest |
| Mocks / stubs / spies | `unittest.mock` (stdlib) |
| Fakes | Hand-rolled classes or dataclasses |
| Property-based | Hypothesis |
| Assertions | pytest's built-in `assert` with `pytest.raises` |
| Mutation testing | mutmut or cosmic-ray |

## Minimal Test Structure

```python
# tests/test_order_service.py
import pytest
from myapp.order_service import OrderService
from tests.fakes import InMemoryOrderRepository

def test_returns_empty_list_when_no_orders_exist():
    repo = InMemoryOrderRepository()
    service = OrderService(repo)

    result = service.list_orders()

    assert result == []
```

## Equivalence Classes and Boundary Testing

```python
import pytest

@pytest.mark.parametrize("age,expected", [
    (-1, False),   # below zero — invalid class
    (0,  False),   # boundary
    (17, False),   # below threshold
    (18, True),    # threshold boundary
    (19, True),    # above threshold — valid class
    (120, True),   # max valid
    (121, False),  # above max
])
def test_is_adult(age, expected):
    assert is_adult(age) == expected
```

## Property-Based Testing (Hypothesis)

```python
from hypothesis import given, strategies as st

@given(st.text())
def test_encode_decode_roundtrip(s):
    assert decode(encode(s)) == s
```

## Test Doubles

```python
from unittest.mock import MagicMock, patch

# Stub
repo = MagicMock()
repo.find_by_id.return_value = user

# Mock — verify interaction
repo.save.assert_called_once_with(user)

# Fake — preferred for stateful deps
class InMemoryOrderRepository:
    def __init__(self):
        self._store = {}
    def save(self, order):
        self._store[order.id] = order
    def find_by_id(self, id):
        return self._store.get(id)
```

## Gotchas

- **`patch` on wrong import path:** patch where the name is **used**, not where it's defined. `patch("myapp.service.datetime")` not `patch("datetime.datetime")`.
- **Patching built-ins:** avoid unless unavoidable. Prefer injecting the dependency instead (pass `clock` as a parameter rather than patching `datetime.now`).
- **Fixture scope:** default to `function` scope for test isolation. `module` or `session` scope is a source of test order dependencies — use only for expensive setup that is genuinely read-only (e.g., a downloaded dataset).
- **`MagicMock` return values:** `MagicMock()` returns a `MagicMock` for any attribute access. Attribute chain mocks (`mock.a.b.c`) can hide missing real behavior. Use fakes for stateful dependencies.
