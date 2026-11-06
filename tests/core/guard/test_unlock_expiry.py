import pytest

from tony.core.guard.unlock_expiry import UnlockExpiry


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_missing_file_is_not_valid(tmp_path):
    assert not UnlockExpiry(tmp_path).is_valid()


def test_refresh_then_is_valid_before_expiry(tmp_path):
    clock = Clock(start=1000.0)
    expiry = UnlockExpiry(tmp_path, clock=clock)
    expiry.refresh(lock_after_min=30)
    clock.now += 60
    assert expiry.is_valid()


def test_is_valid_false_after_expiry(tmp_path):
    clock = Clock(start=1000.0)
    expiry = UnlockExpiry(tmp_path, clock=clock)
    expiry.refresh(lock_after_min=30)
    clock.now += 30 * 60 + 1
    assert not expiry.is_valid()


@pytest.mark.parametrize("content", ["", "not a number", "{}"])
def test_corrupt_file_is_not_valid(tmp_path, content):
    path = tmp_path / "config" / "edith.session"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    assert not UnlockExpiry(tmp_path).is_valid()


def test_clear_removes_the_file_and_is_idempotent(tmp_path):
    expiry = UnlockExpiry(tmp_path)
    expiry.refresh(lock_after_min=30)
    expiry.clear()
    assert not (tmp_path / "config" / "edith.session").exists()
    expiry.clear()


def test_refresh_writes_atomically_no_temp_file_left(tmp_path):
    expiry = UnlockExpiry(tmp_path)
    expiry.refresh(lock_after_min=30)
    assert sorted(p.name for p in (tmp_path / "config").iterdir() if "session" in p.name) == [
        "edith.session"
    ]
