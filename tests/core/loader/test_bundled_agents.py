from pathlib import Path

from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.placeholders import SecretMasker
from tony.core.config.settings import TonyConfig
from tony.core.loader.agent import load_agent
from tony.core.loader.skills import list_skills, read_skill_body
from tony.core.mcp.manager import McpManager
from tony.core.mcp.native import NativeScope
from tony.core.orchestrator.natives import NATIVE_TOOLS

REPO = Path(__file__).resolve().parents[3]


def bundled(name):
    return load_agent(REPO, name, TonyConfig(), native_tools=NATIVE_TOOLS.keys())


def test_bundled_jarvis_loads():
    jarvis = bundled("jarvis")

    assert (jarvis.spec.role, jarvis.spec.model, jarvis.spec.voice.tts) == (
        "front",
        "claude-haiku",
        "kokoro/em_alex",
    )
    assert (jarvis.spec.persona.language, jarvis.spec.persona.tone) == (
        "es",
        "formal, irónico, mayordomo británico; se dirige al usuario como «señor»",
    )
    assert jarvis.tools.mcp_servers == {}
    assert jarvis.tools.native == []


def test_jarvis_prompt_covers_delegation_and_address():
    prompt = bundled("jarvis").spec.system_prompt

    for word in ("delegate", "remember", "set_reply_mode", "«señor»"):
        assert word in prompt


def test_bundled_viernes_persona():
    viernes = bundled("viernes")

    assert viernes.spec.persona.tone == "cercano, ágil y pragmático; humor sutil solo en el resumen"
    assert (viernes.spec.role, viernes.spec.model, viernes.spec.voice.tts) == (
        "worker",
        "claude-sonnet",
        "kokoro/ef_dora",
    )
    assert "resumen" in viernes.spec.system_prompt


def test_bundled_viernes_declares_its_natives():
    assert bundled("viernes").tools.native == ["read_skill", "run_subagent", "ask_user"]


async def test_bundled_viernes_catalog_has_native_ids(tmp_path):
    tools = bundled("viernes").tools.model_copy(update={"mcp_servers": {}})
    scope = NativeScope(root=REPO, agent="viernes")
    natives = {name: NATIVE_TOOLS[name](scope) for name in tools.native}
    manager = McpManager(
        tools,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path,
        native=natives,
    )

    async with manager:
        assert [tool.id for tool in manager.tools] == [
            "tony.read_skill",
            "tony.run_subagent",
            "tony.ask_user",
        ]


def test_viernes_has_a_music_server_launched_with_the_project_python():
    server = bundled("viernes").tools.mcp_servers["music"]

    assert (server.command, server.args) == ("python", ["-m", "tony.core.music"])


def test_viernes_has_the_music_skill():
    body = read_skill_body(REPO, "viernes", "musica")

    assert "music_play" in body and "music_queue" in body


def test_viernes_lists_the_evidence_skill_without_errors():
    skills, errors = list_skills(REPO, "viernes")

    assert errors == []
    [evidencia] = [skill for skill in skills if skill.name == "evidencia"]
    assert evidencia.description


def test_evidence_skill_teaches_the_source_shape():
    body = read_skill_body(REPO, "viernes", "evidencia")

    for term in ("fuentes", "connector", "id", "title", "retrieved_at", "excerpt", "300"):
        assert term in body
