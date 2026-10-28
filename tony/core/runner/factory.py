"""Factory signature of a worker runner: one runner per task, with its native handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tony.core.config import TonySettings
from tony.core.mcp import ConfirmGate
from tony.core.runner.cancel import CancelToken
from tony.core.runner.claude_sdk import ClaudeSdkRunner
from tony.core.runner.ports import AgentRunner
from tony.core.runner.proxy import ToolCaller

WorkerRunnerFactory = Callable[
    [TonySettings, str, ConfirmGate, ToolCaller, CancelToken, Any], AgentRunner
]


def default_worker_runner_factory(
    settings: TonySettings,
    task_id: str,
    gate: ConfirmGate,
    call: ToolCaller,
    token: CancelToken,
    native_handlers: Any = None,
) -> AgentRunner:
    return ClaudeSdkRunner(
        settings=settings,
        task_id=task_id,
        gate=gate,
        call=call,
        cancel_token=token,
        native_handlers=native_handlers,
    )
