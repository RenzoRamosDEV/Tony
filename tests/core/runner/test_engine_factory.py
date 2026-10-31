"""build_runner_factory/build_conversation: engine selection point (design.md D2).

For the `claude_sdk` engine (declared or implicit), both functions must resolve to
exactly the pre-existing plumbing, so introducing the selection point changes no
observable behavior of the current single-engine runtime.
"""

from __future__ import annotations

from pathlib import Path

from tony.core.config import EngineProfile, load_settings
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


def test_litellm_factories_resolve_named_profile():
    from tony.core.runner.litellm_engine import LiteLlmConversation, LiteLlmRunner

    settings = load_settings(None)
    settings.engines["portable"] = EngineProfile(type="litellm", model="gpt-4o")
    spec = make_spec(engine="portable")
    factory = build_runner_factory(settings, spec)
    assert isinstance(factory(settings, "t1", object(), object(), None), LiteLlmRunner)
    assert build_conversation(settings, spec) is LiteLlmConversation
