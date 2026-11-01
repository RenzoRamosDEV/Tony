import json
import shutil
from pathlib import Path

from tests.fakes.servers import fake_fs_entry

REPO = Path(__file__).resolve().parents[3]


def make_viernes_home(tmp_path: Path, extra_servers: dict | None = None) -> tuple[Path, Path]:
    """A TONY_HOME whose Viernes uses the fake filesystem server over a notes folder."""
    home, notes = tmp_path / "home", tmp_path / "notas"
    notes.mkdir()
    (notes / "a.md").write_text("# Nota A\nComprar pan.")
    agent = home / "agents" / "viernes"
    (agent / "tool").mkdir(parents=True)
    shutil.copy(REPO / "agents" / "viernes" / "agent.md", agent / "agent.md")
    servers = {"filesystem": fake_fs_entry(str(notes)), **(extra_servers or {})}
    (agent / "tool" / "tool.json").write_text(json.dumps({"mcpServers": servers}))
    return home, notes
