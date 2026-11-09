from pathlib import Path

from tests.core.guard.shipped_policy import SHIPPED_POLICY_DATA
from tony.core.config.settings import TonyConfig
from tony.core.guard.allow_always import ALLOW_ALWAYS_PREFIX
from tony.core.guard.evaluate import evaluate
from tony.core.guard.policy import Policy, load_policy
from tony.core.loader.agent import load_agent

REPO = Path(__file__).resolve().parents[3]


def test_bundled_edith_loads_as_guard_without_tools():
    agent = load_agent(REPO, "edith", TonyConfig(), native_tools=set())

    assert (agent.spec.role, agent.spec.model) == ("guard", "claude-haiku")
    assert (agent.spec.persona.language, agent.spec.persona.tone) == (
        "es",
        "muy formal, neutral, literal, sin humor",
    )
    assert agent.spec.voice.tts == "kokoro/ef_dora,bf_emma"
    assert (agent.tools.mcp_servers, agent.tools.native) == ({}, [])
    assert not (REPO / "agents" / "edith" / "tool").exists()


def test_system_prompt_states_the_question_template():
    prompt = load_agent(REPO, "edith", TonyConfig(), native_tools=set()).spec.system_prompt

    assert "Acción: <qué>. Regla: <rule id>. ¿Autoriza?" in prompt


def shipped_rules(policy: Policy) -> Policy:
    """The policy without the per-user «Permitir siempre» rules, which are not shipped."""
    own = [rule for rule in policy.rules if not rule.id.startswith(ALLOW_ALWAYS_PREFIX)]
    return policy.model_copy(update={"rules": own})


def test_bundled_policy_equals_the_shipped_example():
    bundled = shipped_rules(load_policy(REPO, "edith"))

    assert bundled == Policy.model_validate(SHIPPED_POLICY_DATA)
    assert [rule.id for rule in bundled.rules] == [
        "filesystem.read_*/allow",
        "filesystem.list_*/allow",
        "filesystem.write_file/confirm",
        "filesystem.write_file/allow",
        "filesystem.delete*/confirm",
        "shell.run/deny",
        "shell.run/confirm",
        "github.search_*/allow",
        "github.*/confirm",
        "google-calendar.list-*/allow",
        "google-calendar.create-event/confirm",
        "google-calendar.*/confirm",
        "gmail.read_email/allow",
        "gmail.send_email/confirm",
        "gmail.*/confirm",
        "gdrive.gdrive_search/allow",
        "gdrive.gsheets_update_cell/confirm",
        "gdrive.*/confirm",
        "obsidian.obsidian_list_vaults/allow",
        "obsidian.obsidian_create_note/confirm",
        "obsidian.*/confirm",
        "music.music_play/confirm",
        "music.*/allow",
        "tony.read_skill/allow",
    ]


def test_bundled_policy_default_is_not_allow():
    assert load_policy(REPO, "edith").default != "allow"


def test_bundled_policy_confirms_starting_music_and_allows_everything_else():
    policy = load_policy(REPO, "edith")

    for tool in ("play", "queue"):
        assert evaluate(policy, f"music.music_{tool}", {"consulta": "x"}).verdict == "confirm"
    for tool in ("search", "pause", "resume", "next", "previous", "volume", "stop", "now_playing"):
        assert evaluate(policy, f"music.music_{tool}", {"consulta": "x"}).verdict == "allow"
