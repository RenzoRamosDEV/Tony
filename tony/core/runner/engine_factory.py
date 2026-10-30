"""Single selection point from an agent's effective engine to its runner/conversation plumbing.

`build_runner_factory`/`build_conversation` are the only places that branch on
`EngineProfile.type` (design.md D2): every other module keeps depending on the
existing `AgentRunner`/`ConversationRunner` ports, unaware that more than one
engine exists.
"""

from __future__ import annotations

from collections.abc import Callable

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate
from tony.core.runner.conversation import ClaudeSdkConversation, ConversationRunner
from tony.core.runner.factory import WorkerRunnerFactory, default_worker_runner_factory
from tony.core.runner.proxy import ToolCaller

ConversationFactory = Callable[[TonySettings, ConfirmGate, ToolCaller], ConversationRunner]


def _engine_type(settings: TonySettings, spec: AgentSpec) -> str:
    return settings.engines[spec.engine].type


def build_runner_factory(settings: TonySettings, spec: AgentSpec) -> WorkerRunnerFactory:
    engine_type = _engine_type(settings, spec)
    if engine_type == "claude_sdk":
        return default_worker_runner_factory
    raise NotImplementedError(f"motor '{engine_type}' todavía no tiene AgentRunner")


def build_conversation(settings: TonySettings, spec: AgentSpec) -> ConversationFactory:
    engine_type = _engine_type(settings, spec)
    if engine_type == "claude_sdk":
        return ClaudeSdkConversation
    raise NotImplementedError(f"motor '{engine_type}' todavía no tiene ConversationRunner")
