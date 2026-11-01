import stat

import pytest

from tony.core.guard.pin import LOCK_FILE, PinStore


def lock(tmp_path):
    return tmp_path / LOCK_FILE


def test_set_writes_an_argon2_hash_without_the_pin(tmp_path):
    PinStore(tmp_path).set("4821")

    content = lock(tmp_path).read_text()
    assert content.startswith("$argon2")
    assert "4821" not in content


def test_lock_file_is_private(tmp_path):
    PinStore(tmp_path).set("4821")

    assert stat.S_IMODE(lock(tmp_path).stat().st_mode) == 0o600


def test_set_replaces_the_previous_hash_and_leaves_no_temp_file(tmp_path):
    store = PinStore(tmp_path)
    store.set("4821")
    first = lock(tmp_path).read_text()

    store.set("7777")

    assert lock(tmp_path).read_text() != first
    assert store.verify("7777") and not store.verify("4821")
    assert sorted(path.name for path in lock(tmp_path).parent.iterdir()) == ["edith.lock"]


@pytest.mark.parametrize(("attempt", "ok"), [("4821", True), ("9999", False), ("", False)])
def test_verify(tmp_path, attempt, ok):
    store = PinStore(tmp_path)
    store.set("4821")

    assert store.verify(attempt) is ok
    assert store.has_valid_lock()


def test_missing_file_is_no_valid_lock(tmp_path):
    store = PinStore(tmp_path)

    assert not store.has_valid_lock()
    assert store.verify("4821") is False


@pytest.mark.parametrize("content", ["", "not a hash", "$argon2id$broken"])
def test_corrupted_file_is_no_valid_lock(tmp_path, content):
    lock(tmp_path).parent.mkdir(parents=True)
    lock(tmp_path).write_text(content)
    store = PinStore(tmp_path)

    assert not store.has_valid_lock()
    assert store.verify("4821") is False
