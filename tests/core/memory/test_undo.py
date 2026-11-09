import hashlib
import json

import pytest

from tony.core.memory.undo import MAX_PREIMAGE_BYTES, UndoStore, UndoUnavailableError

CALL = "6f1c2a3e-1111-4222-8333-444455556666"
WRITE = "filesystem.write_file"


def args_for(path, content="nuevo"):
    return {"path": str(path), "content": content}


def test_keeps_previous_bytes_and_path_sidecar(tmp_path):
    target = tmp_path / "a.md"
    target.write_bytes(b"antes 0123")
    store = UndoStore(tmp_path / "root")

    store.keep(CALL, WRITE, args_for(target))

    assert (tmp_path / "root" / "memory" / "undo" / CALL).read_bytes() == b"antes 0123"
    sidecar = json.loads((tmp_path / "root" / "memory" / "undo" / f"{CALL}.json").read_text())
    assert sidecar == {"path": str(target)}
    assert store.is_undoable(CALL)


def test_files_are_private(tmp_path):
    target = tmp_path / "a.md"
    target.write_text("x")
    store = UndoStore(tmp_path / "root")

    store.keep(CALL, WRITE, args_for(target))

    undo_dir = tmp_path / "root" / "memory" / "undo"
    assert undo_dir.stat().st_mode & 0o777 == 0o700
    assert (undo_dir / CALL).stat().st_mode & 0o777 == 0o600
    assert (undo_dir / f"{CALL}.json").stat().st_mode & 0o777 == 0o600


def test_missing_file_stores_nothing(tmp_path):
    store = UndoStore(tmp_path / "root")

    store.keep(CALL, WRITE, args_for(tmp_path / "absent.md"))

    assert not store.is_undoable(CALL)


@pytest.mark.parametrize(
    ("size", "stored"), [(MAX_PREIMAGE_BYTES, True), (MAX_PREIMAGE_BYTES + 1, False)]
)
def test_size_boundary(tmp_path, size, stored):
    target = tmp_path / "big.txt"
    target.write_bytes(b"a" * size)
    store = UndoStore(tmp_path / "root")

    store.keep(CALL, WRITE, args_for(target))

    assert store.is_undoable(CALL) is stored


def test_non_utf8_file_stores_nothing(tmp_path):
    target = tmp_path / "bin"
    target.write_bytes(b"\xff\xfe\x00")
    store = UndoStore(tmp_path / "root")

    store.keep(CALL, WRITE, args_for(target))

    assert not store.is_undoable(CALL)


def test_other_tools_store_nothing(tmp_path):
    target = tmp_path / "a.md"
    target.write_text("x")
    store = UndoStore(tmp_path / "root")

    store.keep(CALL, "filesystem.delete_file", args_for(target))

    assert not store.is_undoable(CALL)
    assert not (tmp_path / "root" / "memory" / "undo").exists()


def test_expands_user_in_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "n.md").write_text("hola")
    store = UndoStore(tmp_path / "root")

    store.keep(CALL, WRITE, {"path": "~/n.md", "content": "z"})

    assert store.load(CALL).content == "hola"
    assert store.load(CALL).path == "~/n.md"


def test_written_digest_is_sha256_of_utf8_content(tmp_path):
    store = UndoStore(tmp_path)

    digest = store.written_digest(WRITE, {"path": "p", "content": "añadido"})

    assert digest == "sha256=" + hashlib.sha256("añadido".encode()).hexdigest()


def test_written_digest_is_empty_for_other_tools(tmp_path):
    assert UndoStore(tmp_path).written_digest("shell.run", {"command": "ls"}) == ""


@pytest.mark.parametrize("bad", ["../etc/passwd", "abc", CALL + "/x", ""])
def test_load_rejects_non_uuid_ids(tmp_path, bad):
    store = UndoStore(tmp_path)

    assert not store.is_undoable(bad)
    with pytest.raises(UndoUnavailableError):
        store.load(bad)


def test_load_of_unknown_call_raises(tmp_path):
    with pytest.raises(UndoUnavailableError):
        UndoStore(tmp_path).load(CALL)


def test_keep_ignores_ids_that_are_not_uuids(tmp_path):
    target = tmp_path / "a.md"
    target.write_text("x")
    store = UndoStore(tmp_path / "root")

    store.keep("../escape", WRITE, args_for(target))

    assert not (tmp_path / "root" / "memory" / "undo").exists()
    assert not (tmp_path / "root" / "memory" / "escape").exists()
