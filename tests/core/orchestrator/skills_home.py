import json
from pathlib import Path

SUBAGENT_MD = """---
name: {name}
role: worker
model: claude-sonnet
persona: {{language: es, tone: directo}}
voice: {{tts: kokoro/em_alex}}
description: {description}
---
Eres {name}. Resuelve la tarea y responde con el resultado estructurado.
"""


def write_skill(
    home: Path,
    name: str,
    description: str = "Resume notas",
    body: str = "Paso 1...",
    agent: str = "agents/viernes",
) -> None:
    folder = home / agent / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"
    )


def set_native(home: Path, agent: str, native: list[str]) -> None:
    path = home / "agents" / agent / "tool" / "tool.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "native": native}))


def write_subagent(
    home: Path,
    name: str,
    description: str = "Resume textos largos",
    servers: dict | None = None,
    native: list[str] | None = None,
    parent: str = "viernes",
) -> Path:
    folder = home / "agents" / parent / "subagents" / name
    (folder / "tool").mkdir(parents=True, exist_ok=True)
    (folder / "agent.md").write_text(SUBAGENT_MD.format(name=name, description=description))
    (folder / "tool" / "tool.json").write_text(
        json.dumps({"mcpServers": servers or {}, "native": native or []})
    )
    return folder
