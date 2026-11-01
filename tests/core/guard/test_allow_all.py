import pytest

from tony.core.events.messages import Ruling, ToolCall
from tony.core.guard.allow_all import AllowAllGuard
from tony.core.guard.port import Guard


@pytest.mark.parametrize(
    "call",
    [
        ToolCall(task_id="t", agent="viernes", tool="filesystem.read_file", args={"path": "a"}),
        ToolCall(task_id="t", agent="jarvis", tool="filesystem.write_file", args={}),
        ToolCall(task_id="", agent="", tool="tony.now", args={}),
    ],
)
async def test_allows_any_call(call):
    assert await AllowAllGuard().decide(call) == Ruling(verdict="allow", rule="allow_all")


def test_satisfies_guard_protocol():
    guard: Guard = AllowAllGuard()

    assert isinstance(guard, Guard)
