from typing import Any

from tony.core.events.messages import TaskRequest, TaskResult

Event = dict[str, Any]


def task_started(agent: str, task: TaskRequest) -> Event:
    return {"type": "task_started", "agent": agent, "task": task.model_dump(mode="json")}


def tool_call(tool: str, args: dict[str, Any]) -> Event:
    return {"type": "tool_call", "tool": tool, "args": args}


def tool_result(tool: str, *, ok: bool, content: str) -> Event:
    return {"type": "tool_result", "tool": tool, "ok": ok, "content": content}


def token_usage(*, input_tokens: int, output_tokens: int) -> Event:
    return {"type": "token_usage", "input_tokens": input_tokens, "output_tokens": output_tokens}


def task_finished(outcome: str, result: TaskResult) -> Event:
    return {"type": "task_finished", "outcome": outcome, "result": result.model_dump(mode="json")}


def error(source: str, message: str) -> Event:
    return {"type": "error", "source": source, "message": message}
