from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import CONFIG_FILE, TonyConfig
from tony.core.loader.agent import AgentDefinition, load_agent
from tony.core.orchestrator.natives import NATIVE_TOOLS


@dataclass(frozen=True)
class AgentSlots:
    front: AgentDefinition
    worker: AgentDefinition
    guard: AgentDefinition


def resolve_slots(
    root: Path, config: TonyConfig, *, native_tools: Collection[str] = NATIVE_TOOLS.keys()
) -> AgentSlots:
    def load(name: str) -> AgentDefinition:
        return load_agent(root, name, config, native_tools=native_tools)

    front, worker, guard = load(config.front), load(config.worker), load(config.guard)
    if front.spec.role == "guard":
        raise DefinitionError(
            CONFIG_FILE, "front", f"agent '{front.name}' is a guard and cannot be the front agent"
        )
    if worker.spec.role != "worker":
        raise DefinitionError(
            CONFIG_FILE,
            "worker",
            f"agent '{worker.name}' is not a worker (role: {worker.spec.role})",
        )
    return AgentSlots(front=front, worker=worker, guard=guard)
