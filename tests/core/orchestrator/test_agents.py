import shutil
from pathlib import Path

import pytest

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import TonyConfig
from tony.core.orchestrator.agents import resolve_slots

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def root(tmp_path):
    shutil.copytree(REPO / "agents", tmp_path / "agents")
    return tmp_path


def test_default_slots(root):
    slots = resolve_slots(root, TonyConfig())

    assert (slots.front.name, slots.worker.name, slots.guard.name) == ("jarvis", "viernes", "edith")
    assert (slots.front.spec.role, slots.worker.spec.role, slots.guard.spec.role) == (
        "front",
        "worker",
        "guard",
    )


def test_viernes_may_be_the_front_agent(root):
    slots = resolve_slots(root, TonyConfig(front="viernes"))

    assert slots.front.name == "viernes"


@pytest.mark.parametrize(
    ("key", "agent"), [("front", "edith"), ("worker", "jarvis"), ("worker", "edith")]
)
def test_invalid_slot_is_rejected_naming_the_config_and_key(root, key, agent):
    with pytest.raises(DefinitionError) as raised:
        resolve_slots(root, TonyConfig(**{key: agent}))

    assert (raised.value.file, raised.value.field) == ("config/tony.yaml", key)
    assert agent in str(raised.value)


def test_missing_agent_folder_propagates_the_loader_error(root):
    with pytest.raises(DefinitionError, match="agents/nadie/"):
        resolve_slots(root, TonyConfig(front="nadie"))
