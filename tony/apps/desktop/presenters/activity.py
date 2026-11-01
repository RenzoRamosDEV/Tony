from dataclasses import dataclass, field

from tony.apps.desktop.presenters.observable import Observable
from tony.core.events.core_events import Event

DOWN_COLOUR = "#D93025"
RUNNING = "en curso"


@dataclass
class ToolNode:
    tool: str
    verdict: str
    user_decision: str | None

    @property
    def label(self) -> str:
        decision = f" ({self.user_decision})" if self.user_decision else ""
        return f"{self.tool} — {self.verdict}{decision}"


@dataclass
class SubagentNode:
    name: str
    calls: list[ToolNode] = field(default_factory=list)


@dataclass
class TaskNode:
    task_id: str
    agent: str
    objetivo: str
    calls: list[ToolNode] = field(default_factory=list)
    subagents: list[SubagentNode] = field(default_factory=list)
    summary: str = RUNNING

    @property
    def label(self) -> str:
        return f"{self.agent}: {self.objetivo}"

    def subagent(self, name: str) -> SubagentNode:
        found = next((node for node in self.subagents if node.name == name), None)
        if found is None:
            found = SubagentNode(name)
            self.subagents.append(found)
        return found


@dataclass
class ServerRow:
    agent: str
    server: str
    down: bool
    reason: str | None

    @property
    def label(self) -> str:
        state = f"caído: {self.reason}" if self.down else "activo"
        return f"{self.agent}/{self.server} — {state}"

    @property
    def colour(self) -> str | None:
        return DOWN_COLOUR if self.down else None


class ActivityPresenter(Observable):
    """Activity zone state: delegated tasks with their tool calls, and MCP server status."""

    def __init__(self) -> None:
        super().__init__()
        self._tasks: dict[str, TaskNode] = {}
        self._servers: dict[tuple[str, str], ServerRow] = {}

    @property
    def tasks(self) -> list[TaskNode]:
        return list(self._tasks.values())

    @property
    def servers(self) -> list[ServerRow]:
        return list(self._servers.values())

    def apply(self, event: Event) -> None:
        kind = event["type"]
        if kind == "task_started":
            self._tasks[event["task_id"]] = TaskNode(
                event["task_id"], event["agent"], event["objetivo"]
            )
        elif kind == "tool_call" and event["task_id"] in self._tasks:
            self._add_call(self._tasks[event["task_id"]], event)
        elif kind == "result" and event["scope"] == "task" and event["task_id"] in self._tasks:
            self._tasks[event["task_id"]].summary = _summary(event)
        elif kind == "mcp_status":
            key = (event["agent"], event["server"])
            self._servers[key] = ServerRow(*key, down=not event["up"], reason=event["reason"])
        else:
            return
        self._changed()

    def _add_call(self, task: TaskNode, event: Event) -> None:
        node = ToolNode(event["tool"], event["verdict"], event["user_decision"])
        _, _, subagent = event["agent"].partition("/")
        (task.subagent(subagent).calls if subagent else task.calls).append(node)


def _summary(event: Event) -> str:
    tokens = event["input_tokens"] + event["output_tokens"]
    return f"{event['outcome']} · {tokens} tokens · {event['elapsed_ms'] / 1000:.1f} s"
