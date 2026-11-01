import json
from datetime import UTC, datetime

import pytest

from tests.core.orchestrator.skills_home import set_native, write_skill, write_subagent
from tests.core.orchestrator.tony_home import make_tony_home
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_chat import FakeChatEngine
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.pin import FakePinPrompt
from tony.core.config.placeholders import SecretMasker
from tony.core.config.settings import load_config
from tony.core.events.messages import TaskRequest
from tony.core.guard.pin import PinStore
from tony.core.guard.policy import Auth
from tony.core.guard.session import EdithSession, SessionGate
from tony.core.memory.history import HistoryStore
from tony.core.orchestrator.agents import resolve_slots
from tony.core.orchestrator.conversation import Conversation
from tony.core.orchestrator.runner import RunDeps, run_task

TASK_ID = "f" * 32
REQUEST = TaskRequest(objetivo="Resume a.md")
OK = {"resumen": "ok", "datos": None, "pasos": [], "errores": []}
FIXED = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def deps_for(home, engine, published):
    return RunDeps(
        root=home,
        engine=engine,
        environ={},
        task_id_factory=lambda: TASK_ID,
        clock=lambda: FIXED,
        publish=published.append,
    )


async def run(home, steps=None, published=None):
    engine = FakeModelEngine(steps or [Final(structured=OK)])
    published = [] if published is None else published
    result = await run_task("viernes", REQUEST, deps_for(home, engine, published))
    return engine, result


def log_lines(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_skills_listed_and_broken_skill_reported(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    set_native(home, "viernes", ["read_skill"])
    write_skill(home, "resumir", "Resume notas en tres viñetas", "Paso 1...")
    (home / "agents/viernes/skills/roto").mkdir()
    (home / "agents/viernes/skills/roto/SKILL.md").write_text("sin frontmatter\n")
    published = []

    engine, result = await run(home, published=published)

    prompt = engine.spec.system_prompt
    assert "## Skills\n\n- resumir: Resume notas en tres viñetas" in prompt
    assert "roto" not in prompt and "Paso 1..." not in prompt
    assert result.resumen == "ok"
    file = "agents/viernes/skills/roto/SKILL.md"
    logged = [line for line in log_lines(home) if line["type"] == "error"]
    assert [line["source"] for line in logged] == ["skills"]
    assert file in logged[0]["message"]
    errors = [event for event in published if event["type"] == "error"]
    assert [(event["source"], file in event["message"]) for event in errors] == [("skills", True)]


async def test_no_section_without_read_skill(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    write_skill(home, "resumir")
    write_subagent(home, "resumidor")

    engine, _ = await run(home)

    assert "## Skills" not in engine.spec.system_prompt
    assert "## Subagentes" not in engine.spec.system_prompt


async def test_skill_added_between_tasks(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    set_native(home, "viernes", ["read_skill"])
    write_skill(home, "resumir")

    first, _ = await run(home)
    write_skill(home, "nueva", "Nueva habilidad")
    second, _ = await run(home)

    assert "nueva" not in first.spec.system_prompt
    assert "- nueva: Nueva habilidad" in second.spec.system_prompt


async def test_subagents_listed_with_run_subagent(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    set_native(home, "viernes", ["run_subagent"])
    write_subagent(home, "resumidor", "Resume textos largos")

    engine, _ = await run(home)

    assert "## Subagentes\n\n- resumidor: Resume textos largos" in engine.spec.system_prompt
    assert "## Skills" not in engine.spec.system_prompt


async def test_read_skill_call_judged_and_audited(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    set_native(home, "viernes", ["read_skill"])
    write_skill(home, "resumir", body="Paso 1...")
    steps = [CallTool("tony.read_skill", {"name": "resumir"}), Final(structured=OK)]

    engine, _ = await run(home, steps)

    assert engine.replies[0].text == "Paso 1..."
    audit = [json.loads(line) for line in (home / "logs/audit.jsonl").read_text().splitlines()]
    assert [(line["tool"], line["verdict"], line["rule"], line["agent"]) for line in audit] == [
        ("tony.read_skill", "allow", "tony.read_skill/allow", "viernes")
    ]


async def test_front_turn_applies_sections(tmp_path):
    home, _ = make_tony_home(tmp_path)
    set_native(home, "jarvis", ["read_skill", "run_subagent"])
    write_skill(home, "saludar", "Saluda", agent="agents/jarvis")
    write_subagent(home, "ayudante", "Ayuda", parent="jarvis")
    config = load_config(home)
    chat = FakeChatEngine()
    conversation = Conversation(
        slots=resolve_slots(home, config),
        config=config,
        deps=RunDeps(root=home, engine=FakeModelEngine([]), environ={}),
        chat_engine=chat,
        gate=SessionGate(
            EdithSession(Auth(pin_required=False), PinStore(home)), FakePinPrompt(), timeout_s=1
        ),
        history=HistoryStore(home, SecretMasker()),
        conversation_id="c1",
    )

    await conversation.handle("hola")
    write_skill(home, "despedir", "Despide", agent="agents/jarvis")
    await conversation.handle("adiós")

    first, second = chat.system_prompts
    assert "## Skills\n\n- saludar: Saluda" in first
    assert "## Subagentes\n\n- ayudante: Ayuda" in first
    assert "despedir" not in first and "- despedir: Despide" in second
