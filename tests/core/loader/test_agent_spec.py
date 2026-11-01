import pytest
import yaml

from tony.core.config.errors import DefinitionError
from tony.core.loader.agent_md import AgentSpec, parse_agent

FILE = "agents/viernes/agent.md"
MODELS = {"claude-sonnet": "claude-sonnet-5-5", "claude-haiku": "claude-haiku-5-5"}


def frontmatter(**overrides):
    data = {
        "name": "viernes",
        "role": "worker",
        "model": "claude-sonnet",
        "persona": {"language": "es", "tone": "directo"},
        "voice": {"tts": "kokoro/em_alex"},
    }
    data.update(overrides)
    return data


def render(data, body="Eres Viernes."):
    return f"---\n{yaml.safe_dump(data)}---\n{body}\n"


def parse(data):
    return parse_agent(render(data), folder="viernes", file=FILE, models=MODELS)


def field_error(data):
    with pytest.raises(DefinitionError) as info:
        parse(data)
    assert info.value.file == FILE
    return info.value.field


def test_valid_agent_exposes_fields_and_prompt():
    spec = parse(frontmatter())

    assert spec == AgentSpec(
        name="viernes",
        role="worker",
        model="claude-sonnet",
        persona={"language": "es", "tone": "directo"},
        voice={"tts": "kokoro/em_alex"},
        system_prompt="Eres Viernes.",
    )


@pytest.mark.parametrize("role", ["front", "worker", "guard"])
def test_accepts_every_role(role):
    assert parse(frontmatter(role=role)).role == role


@pytest.mark.parametrize("missing", ["name", "role", "model", "persona", "voice"])
def test_missing_top_level_field(missing):
    data = frontmatter()
    del data[missing]

    assert field_error(data) == missing


@pytest.mark.parametrize(
    ("section", "missing"), [("persona", "language"), ("persona", "tone"), ("voice", "tts")]
)
def test_missing_nested_field(section, missing):
    data = frontmatter()
    del data[section][missing]

    assert field_error(data) == f"{section}.{missing}"


def test_name_must_match_folder():
    assert field_error(frontmatter(name="friday")) == "name"


def test_invalid_role():
    assert field_error(frontmatter(role="helper")) == "role"


def test_unknown_top_level_field():
    assert field_error(frontmatter(max_steps=20)) == "max_steps"


def test_unknown_nested_field():
    data = frontmatter()
    data["persona"]["address"] = "señor"

    assert field_error(data) == "persona.address"


@pytest.mark.parametrize("tts", ["kokoro/x", "kokoro/em_alex"])
def test_valid_voice(tts):
    assert parse(frontmatter(voice={"tts": tts})).voice.tts == tts


@pytest.mark.parametrize("tts", ["em_alex", "kokoro/", "kokoro", "piper/em_alex", "kokoro/ x", ""])
def test_malformed_voice(tts):
    assert field_error(frontmatter(voice={"tts": tts})) == "voice.tts"


def test_model_alias_not_configured():
    assert field_error(frontmatter(model="claude-opus")) == "model"


def test_model_id_instead_of_alias_rejected():
    assert field_error(frontmatter(model="claude-sonnet-5-5")) == "model"


def test_wrong_type_for_section():
    assert field_error(frontmatter(persona="es")) == "persona"
