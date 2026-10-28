"""Conversation evals: the front through ChatSession (fixtures) or the real model + judge."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.conftest import LIVE, conversation_evals, conversation_parts, judge_one_shot, load_spec
from tests.fakes.channels import ListChannel
from tony.core.channels.session import ChatSession, Memory
from tony.core.evals.assertions import check_turn
from tony.core.evals.judge import judge
from tony.core.memory.conversations import ConversationStore
from tony.core.memory.preferences import PreferencesStore
from tony.core.memory.settings import SettingsStore
from tony.core.orchestrator.orchestrator import Orchestrator

EVALS = conversation_evals()


@pytest.mark.evals
@pytest.mark.parametrize("eval", EVALS, ids=[e.id for e in EVALS])
async def test_conversation(eval, settings, agents_dir, env, tmp_path: Path) -> None:
    front = load_spec(agents_dir, settings.front, settings, env)
    worker = load_spec(agents_dir, settings.worker, settings, env)
    runner, factory, clock = conversation_parts(eval, worker, settings, tmp_path)
    orchestrator = Orchestrator(factory, settings.limits, clock=clock)
    memory = Memory(
        preferences=PreferencesStore(tmp_path / "memory" / "preferences.md"),
        settings=SettingsStore(tmp_path / "memory" / "settings.json"),
        conversations=ConversationStore(tmp_path / "memory" / "conversations.sqlite"),
    )
    session = ChatSession(front, runner, orchestrator, ListChannel(), memory, settings, clock=clock)
    await session.start(memory.conversations.start_conversation("evals"))
    try:
        for number, turn in enumerate(eval.turns, 1):
            before = len(orchestrator.tasks)
            reply = await session.handle(turn.user)
            assert reply is not None, f"{eval.id} turno {number}: sin respuesta"
            delegated = len(orchestrator.tasks) > before
            failures = check_turn(reply.display_text, delegated, turn.expect)
            if LIVE and turn.expect.judge:
                verdict = await judge(
                    await judge_one_shot(settings), turn.expect.judge, reply.display_text
                )
                if not verdict.passed:
                    failures.append(f"juez: {verdict.reason}")
            assert failures == [], f"{eval.id} turno {number}: " + "; ".join(failures)
    finally:
        await session.close()
        memory.conversations.close()
