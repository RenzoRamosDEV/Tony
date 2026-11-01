from tony.apps.desktop.presenters.activity import DOWN_COLOUR, ActivityPresenter
from tony.core.events import core_events as ev
from tony.core.events.messages import Ruling, TaskResult

ALLOW = Ruling(verdict="allow", rule="filesystem.read_*/allow")


def make():
    presenter, changes = ActivityPresenter(), []
    presenter.subscribe(lambda: changes.append(True))
    return presenter, changes


def call(agent="viernes", tool="filesystem.read_file", ruling=ALLOW, task="t1"):
    return ev.tool_call(task, agent, tool, "{}", ruling)


def test_task_started_creates_a_task_node():
    presenter, changes = make()

    presenter.apply(ev.task_started("t1", "viernes", "Lista mis notas"))

    [task] = presenter.tasks
    assert (task.task_id, task.label, task.calls, task.summary) == (
        "t1",
        "viernes: Lista mis notas",
        [],
        "en curso",
    )
    assert changes == [True]


def test_tool_calls_are_children_with_verdict_and_user_decision():
    presenter, _ = make()
    presenter.apply(ev.task_started("t1", "viernes", "x"))

    presenter.apply(call())
    confirmed = Ruling(verdict="confirm", rule="r", user_decision="allow")
    presenter.apply(call(tool="filesystem.delete_file", ruling=confirmed))

    assert [node.label for node in presenter.tasks[0].calls] == [
        "filesystem.read_file — allow",
        "filesystem.delete_file — confirm (allow)",
    ]


def test_subagent_calls_nest_under_a_subagent_node():
    presenter, _ = make()
    presenter.apply(ev.task_started("t1", "viernes", "x"))

    presenter.apply(call(agent="viernes/resumidor"))
    presenter.apply(call(agent="viernes/resumidor", tool="filesystem.list_directory"))
    presenter.apply(call(agent="viernes/traductor"))

    task = presenter.tasks[0]
    assert task.calls == []
    assert [(sub.name, [c.tool for c in sub.calls]) for sub in task.subagents] == [
        ("resumidor", ["filesystem.read_file", "filesystem.list_directory"]),
        ("traductor", ["filesystem.read_file"]),
    ]


def test_task_result_sets_tokens_and_elapsed():
    presenter, _ = make()
    presenter.apply(ev.task_started("t1", "viernes", "x"))

    presenter.apply(
        ev.task_result(
            "t1",
            "viernes",
            "ok",
            TaskResult(resumen=""),
            input_tokens=120,
            output_tokens=30,
            elapsed_ms=2500,
        )
    )

    assert presenter.tasks[0].summary == "ok · 150 tokens · 2.5 s"


def test_events_for_unknown_tasks_are_ignored():
    presenter, changes = make()

    presenter.apply(call(task="nope"))
    presenter.apply(
        ev.task_result(
            "nope", "v", "ok", TaskResult(resumen=""), input_tokens=0, output_tokens=0, elapsed_ms=0
        )
    )

    assert (presenter.tasks, changes) == ([], [])


def test_mcp_status_rows_marked_red_when_down():
    presenter, _ = make()

    presenter.apply(ev.mcp_status("viernes", "filesystem", up=True, reason=None))
    presenter.apply(ev.mcp_status("viernes", "broken", up=False, reason="no such command"))
    presenter.apply(ev.mcp_status("viernes", "filesystem", up=False, reason="crashed"))

    rows = [(r.agent, r.server, r.down, r.label, r.colour) for r in presenter.servers]
    assert rows == [
        ("viernes", "filesystem", True, "viernes/filesystem — caído: crashed", DOWN_COLOUR),
        ("viernes", "broken", True, "viernes/broken — caído: no such command", DOWN_COLOUR),
    ]


def test_up_server_row_has_no_colour():
    presenter, _ = make()

    presenter.apply(ev.mcp_status("viernes", "filesystem", up=True, reason=None))

    [row] = presenter.servers
    assert (row.down, row.label, row.colour) == (False, "viernes/filesystem — activo", None)


def test_unrelated_events_change_nothing():
    presenter, changes = make()

    presenter.apply(ev.token("jarvis", "x"))

    assert changes == []
