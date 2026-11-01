import json

import pytest

from tests.core.orchestrator.skills_home import write_skill, write_subagent
from tests.core.orchestrator.tony_home import make_tony_home
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_chat import FakeChatEngine
from tests.fakes.fake_engine import ByAgentEngine, CallTool, FakeModelEngine, Final
from tests.fakes.pin import FakePinPrompt
from tests.fakes.servers import fake_fs_entry
from tony.core.config.errors import DefinitionError
from tony.core.config.placeholders import SecretMasker
from tony.core.config.reload import StaticPolicy
from tony.core.config.settings import load_config
from tony.core.events.messages import TaskRequest
from tony.core.guard.pin import PinStore
from tony.core.guard.policy import Auth, Policy
from tony.core.guard.session import EdithSession, SessionGate
from tony.core.loader.tool_json import ToolSpec
from tony.core.memory.history import HistoryStore
from tony.core.orchestrator.agents import resolve_slots
from tony.core.orchestrator.conversation import Conversation
from tony.core.orchestrator.runner import RunDeps, run_task

REQUEST = TaskRequest(objetivo="Lee a.md")
OK = {"resumen": "ok"}
READ = CallTool("filesystem.read_file", {"path": "a.md"})
NO_READ = Policy.model_validate(
    {
        "default": "allow",
        "rules": [{"match": "filesystem.read_*", "verdict": "deny", "id": "no-read"}],
    }
)


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


class DictSpecs:
    def __init__(self, specs):
        self.specs = specs
        self.asked = []

    def spec_for(self, key):
        self.asked.append(key)
        return self.specs[key]


def spec(servers=None, native=None):
    return ToolSpec.model_validate({"mcpServers": servers or {}, "native": native or []})


def audit(home):
    lines = (home / "logs" / "audit.jsonl").read_text().splitlines()
    return [(line["agent"], line["tool"], line["rule"]) for line in map(json.loads, lines)]


async def test_policy_source_used_and_invalid_policy_file_ignored(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    (home / "agents/edith/policy.yaml").write_text("default: [roto\n")
    engine = FakeModelEngine([READ, Final(structured=OK)])

    await run_task(
        "viernes",
        REQUEST,
        RunDeps(root=home, engine=engine, environ={}, policy_source=StaticPolicy(NO_READ)),
    )

    assert audit(home) == [("viernes", "filesystem.read_file", "no-read")]
    assert engine.replies[0].is_error


async def test_without_policy_source_invalid_policy_file_fails(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    (home / "agents/edith/policy.yaml").write_text("default: [roto\n")

    with pytest.raises(DefinitionError) as info:
        await run_task("viernes", REQUEST, RunDeps(root=home, engine=FakeModelEngine([])))
    assert info.value.file == "agents/edith/policy.yaml"


async def test_tool_specs_used_and_invalid_tool_json_ignored(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    (home / "agents/viernes/tool/tool.json").write_text('{"mcpServers": {}, "confirm": []}')
    specs = DictSpecs({"viernes": spec({"notas": fake_fs_entry(str(notes))})})
    engine = FakeModelEngine([Final(structured=OK)])

    await run_task(
        "viernes", REQUEST, RunDeps(root=home, engine=engine, environ={}, tool_specs=specs)
    )

    assert "notas.read_file" in engine.offered
    assert specs.asked == ["viernes"]


async def test_subagent_tool_spec_from_source(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    sub = write_subagent(home, "resumidor")
    (sub / "tool" / "tool.json").write_text("roto")
    specs = DictSpecs(
        {
            "viernes": spec({"filesystem": fake_fs_entry(str(notes))}, ["run_subagent"]),
            "viernes/resumidor": spec({"notas": fake_fs_entry(str(notes))}),
        }
    )
    call = CallTool("tony.run_subagent", {"name": "resumidor", "tarea": {"objetivo": "x"}})
    engine = ByAgentEngine(
        {"viernes": [call, Final(structured=OK)], "resumidor": [Final(structured=OK)]}
    )

    await run_task(
        "viernes", REQUEST, RunDeps(root=home, engine=engine, environ={}, tool_specs=specs)
    )

    assert engine.engines["viernes"].replies[0].is_error is False
    assert "notas.read_file" in engine.engines["resumidor"].offered


async def test_front_turn_uses_tool_specs(tmp_path):
    home, _ = make_tony_home(tmp_path)
    write_skill(home, "saludar", "Saluda", agent="agents/jarvis")
    config = load_config(home)
    specs = DictSpecs({"jarvis": spec(native=["read_skill"])})
    chat = FakeChatEngine()
    conversation = Conversation(
        slots=resolve_slots(home, config),
        config=config,
        deps=RunDeps(root=home, engine=FakeModelEngine([]), environ={}, tool_specs=specs),
        chat_engine=chat,
        gate=SessionGate(
            EdithSession(Auth(pin_required=False), PinStore(home)), FakePinPrompt(), timeout_s=1
        ),
        history=HistoryStore(home, SecretMasker()),
        conversation_id="c1",
    )

    await conversation.handle("hola")

    assert "- saludar: Saluda" in chat.system_prompts[0]
    assert "tony.read_skill" in chat.offered[0]
