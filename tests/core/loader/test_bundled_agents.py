from pathlib import Path

from tony.core.config.settings import TonyConfig
from tony.core.loader.agent import load_agent

REPO = Path(__file__).resolve().parents[3]


def bundled(name):
    return load_agent(REPO, name, TonyConfig(), native_tools=())


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
    assert (viernes.spec.role, viernes.spec.model) == ("worker", "claude-sonnet")
    assert "resumen" in viernes.spec.system_prompt
