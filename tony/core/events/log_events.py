from typing import Any, Literal

from tony.core.events.messages import TaskRequest, TaskResult

Event = dict[str, Any]
Outcome = Literal["ok", "error", "timeout", "cancelled"]


def task_started(agent: str, task: TaskRequest) -> Event:
    return {"type": "task_started", "agent": agent, "task": task.model_dump(mode="json")}


def tool_call(agent: str, tool: str, args: dict[str, Any]) -> Event:
    return {"type": "tool_call", "agent": agent, "tool": tool, "args": args}


def tool_result(agent: str, tool: str, *, ok: bool, content: str) -> Event:
    return {"type": "tool_result", "agent": agent, "tool": tool, "ok": ok, "content": content}


def subagent_started(agent: str, task: TaskRequest) -> Event:
    return {"type": "subagent_started", "agent": agent, "task": task.model_dump(mode="json")}


def subagent_finished(agent: str, outcome: Outcome, result: TaskResult) -> Event:
    return {
        "type": "subagent_finished",
        "agent": agent,
        "outcome": outcome,
        "result": result.model_dump(mode="json"),
    }


def token_usage(*, input_tokens: int, output_tokens: int) -> Event:
    return {"type": "token_usage", "input_tokens": input_tokens, "output_tokens": output_tokens}


def token_alert(*, total_tokens: int, limit: int) -> Event:
    return {"type": "token_alert", "total_tokens": total_tokens, "limit": limit}


def task_finished(outcome: Outcome, result: TaskResult) -> Event:
    return {"type": "task_finished", "outcome": outcome, "result": result.model_dump(mode="json")}


def error(source: str, message: str) -> Event:
    return {"type": "error", "source": source, "message": message}
