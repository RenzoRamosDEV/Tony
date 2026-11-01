"""Offline acceptance: Jarvis delegates to Viernes under the shipped policy."""

import json

import pytest

from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.pin import FakePinPrompt
from tony.core.config.placeholders import SecretMasker
from tony.core.config.settings import load_config
from tony.core.guard.pin import PinStore
from tony.core.guard.policy import Auth
from tony.core.guard.session import EdithSession, SessionGate
from tony.core.memory.history import HistoryStore
from tony.core.orchestrator.agents import resolve_slots
from tony.core.orchestrator.conversation import Conversation
from tony.core.orchestrator.runner import RunDeps

RESULT = {
    "resumen": "Tienes una nota sobre la compra.",
    "datos": {"a.md": "# Nota A\nComprar pan."},
    "pasos": ["listar", "leer"],
    "errores": [],
}


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


async def test_jarvis_delegates_a_listing_and_reading_to_viernes(tmp_path):
    home, _ = make_tony_home(tmp_path)
    chat = FakeChatEngine(
        [
            CallTool("tony.delegate", {"objetivo": "Resume mis notas"}),
            Say("Tiene una nota sobre la compra, señor."),
        ]
    )
    worker = FakeModelEngine(
        [
            CallTool("filesystem.list_directory", {"path": "."}),
            CallTool("filesystem.read_file", {"path": "a.md"}),
            Final(structured=RESULT),
        ]
    )
    published = []
    config = load_config(home)
    history = HistoryStore(home, SecretMasker())
    conversation = Conversation(
        slots=resolve_slots(home, config),
        config=config,
        deps=RunDeps(root=home, engine=worker, environ={}, publish=published.append),
        chat_engine=chat,
        gate=SessionGate(
            EdithSession(Auth(pin_required=False), PinStore(home)), FakePinPrompt(), timeout_s=1
        ),
        history=history,
        conversation_id="c1",
    )

    reply = await conversation.handle("¿Qué hay en mis notas?")
    history.close()

    assert reply == "Tiene una nota sobre la compra, señor."
    assert json.loads(chat.replies[0].text) == RESULT
    assert not [tool for tool in worker.offered if tool.startswith("tony.")]
    audit = [json.loads(raw) for raw in (home / "logs" / "audit.jsonl").read_text().splitlines()]
    assert [(line["agent"], line["tool"]) for line in audit] == [
        ("viernes", "filesystem.list_directory"),
        ("viernes", "filesystem.read_file"),
    ]
    kinds = [event["type"] for event in published]
    assert kinds.index("task_started") < kinds.index("token")
    assert published[-1]["scope"] == "turn"
