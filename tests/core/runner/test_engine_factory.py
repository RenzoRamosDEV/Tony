"""build_runner_factory/build_conversation: engine selection point (design.md D2).

For the `claude_sdk` engine (declared or implicit), both functions must resolve to
exactly the pre-existing plumbing, so introducing the selection point changes no
observable behavior of the current single-engine runtime.
"""

from __future__ import annotations

from pathlib import Path

from tony.core.config import load_settings
from tony.core.loader import AgentSpec
from tony.core.runner.conversation import ClaudeSdkConversation
from tony.core.runner.engine_factory import build_conversation, build_runner_factory
from tony.core.runner.factory import default_worker_runner_factory


def make_spec(engine: str = "claude_sdk") -> AgentSpec:
    return AgentSpec(
        name="viernes", role="worker", model="claude-sonnet", engine=engine, path=Path("/tmp/x")
    )


def test_build_runner_factory_resolves_claude_sdk_to_the_default_factory() -> None:
    settings = load_settings(None)

    assert build_runner_factory(settings, make_spec()) is default_worker_runner_factory


def test_build_conversation_resolves_claude_sdk_to_the_claude_sdk_conversation() -> None:
    settings = load_settings(None)

    assert build_conversation(settings, make_spec()) is ClaudeSdkConversation
