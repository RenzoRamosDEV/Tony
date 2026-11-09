import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.memory.actions import ActionJournal
from tony.core.memory.undo import UndoStore
from tony.core.recovery.undo import UndoRefusedError, plan_undo

WRITE = "filesystem.write_file"


@pytest.fixture
def parts(tmp_path):
    journal = ActionJournal(tmp_path / "root", SecretMasker())
    yield journal, UndoStore(tmp_path / "root"), tmp_path / "f.txt"
    journal.close()


def do_write(journal, store, target, new="nuevo", *, state="succeeded", tool=WRITE):
    """What the proxy does around a write, then the write itself."""
    args = {"path": str(target), "content": new}
    call_id = journal.prepared("t1", "viernes", tool, "d")
    store.keep(call_id, tool, args)
    target.write_text(new)
    journal.transition(call_id, state, store.written_digest(tool, args))
    return call_id


def test_plan_restores_previous_content_for_an_unchanged_file(parts):
    journal, store, target = parts
    target.write_text("antes")
    call_id = do_write(journal, store, target)

    plan = plan_undo(journal, store, call_id)

    assert plan.agent == "viernes"
    assert plan.args == {"path": str(target), "content": "antes"}


def test_changed_file_is_refused(parts):
    journal, store, target = parts
    target.write_text("antes")
    call_id = do_write(journal, store, target)
    target.write_text("otra cosa")

    with pytest.raises(UndoRefusedError, match="file changed since the action"):
        plan_undo(journal, store, call_id)


def test_missing_file_counts_as_changed(parts):
    journal, store, target = parts
    target.write_text("antes")
    call_id = do_write(journal, store, target)
    target.unlink()

    with pytest.raises(UndoRefusedError, match="file changed since the action"):
        plan_undo(journal, store, call_id)


def test_unknown_call(parts):
    journal, store, _ = parts

    with pytest.raises(UndoRefusedError, match="unknown action nope"):
        plan_undo(journal, store, "nope")


def test_action_that_did_not_succeed(parts):
    journal, store, target = parts
    target.write_text("antes")
    call_id = do_write(journal, store, target, state="failed")

    with pytest.raises(UndoRefusedError, match="is not succeeded"):
        plan_undo(journal, store, call_id)


def test_other_tool_is_not_undoable(parts):
    journal, store, target = parts
    call_id = do_write(journal, store, target, tool="shell.run")

    with pytest.raises(UndoRefusedError, match="^not undoable$"):
        plan_undo(journal, store, call_id)


def test_missing_pre_image(parts):
    journal, store, target = parts
    call_id = do_write(journal, store, target)

    with pytest.raises(UndoRefusedError, match=f"no stored content for {call_id}"):
        plan_undo(journal, store, call_id)
