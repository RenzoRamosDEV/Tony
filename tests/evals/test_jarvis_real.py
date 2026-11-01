import json
import shutil

import pytest

from tests.core.orchestrator.viernes_home import REPO
from tests.fakes.pin import FakePinPrompt
from tony.core.config.placeholders import SecretMasker
from tony.core.config.settings import load_config
from tony.core.guard.pin import PinStore
from tony.core.guard.policy import Auth
from tony.core.guard.session import EdithSession, SessionGate
from tony.core.memory.history import HistoryStore
from tony.core.orchestrator.agents import resolve_slots
from tony.core.orchestrator.claude_engine import ClaudeEngine
from tony.core.orchestrator.conversation import Conversation
from tony.core.orchestrator.runner import RunDeps


@pytest.mark.evals
@pytest.mark.timeout(300)
async def test_jarvis_delegates_a_listing_and_answers_in_spanish(tmp_path):
    if shutil.which("npx") is None:
        pytest.skip("npx is required for @modelcontextprotocol/server-filesystem")
    home, notes = tmp_path / "home", tmp_path / "notas"
    notes.mkdir()
    (notes / "compra.md").write_text("# Lista de la compra\n- pan\n")
    (notes / "viaje.md").write_text("# Viaje\n- billetes\n")
    for name in ("jarvis", "edith"):
        shutil.copytree(REPO / "agents" / name, home / "agents" / name)
    viernes = home / "agents" / "viernes"
    (viernes / "tool").mkdir(parents=True)
    shutil.copy(REPO / "agents" / "viernes" / "agent.md", viernes / "agent.md")
    server = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(notes)],
    }
    (viernes / "tool" / "tool.json").write_text(json.dumps({"mcpServers": {"filesystem": server}}))
    published = []
    config = load_config(home)
    history = HistoryStore(home, SecretMasker())
    conversation = Conversation(
        slots=resolve_slots(home, config),
        config=config,
        deps=RunDeps(root=home, engine=ClaudeEngine(), publish=published.append),
        chat_engine=ClaudeEngine(),
        gate=SessionGate(
            EdithSession(Auth(pin_required=False), PinStore(home)), FakePinPrompt(), timeout_s=1
        ),
        history=history,
        conversation_id="eval",
    )

    reply = await conversation.handle(f"¿Qué ficheros hay en la carpeta {notes}?")
    history.close()

    assert any(event["type"] == "task_started" for event in published)
    assert reply and "compra" in reply.lower()
    assert any(word in reply.lower() for word in ("señor", "notas", "ficheros", "carpeta"))
