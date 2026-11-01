import json
import shutil

import pytest

from tests.core.orchestrator.viernes_home import REPO
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.claude_engine import ClaudeEngine
from tony.core.orchestrator.results import UNSTRUCTURED
from tony.core.orchestrator.runner import RunDeps, run_task

TASK_ID = "e" * 32


@pytest.mark.evals
@pytest.mark.timeout(300)
async def test_viernes_lists_and_reads_notes_with_the_real_model(tmp_path):
    if shutil.which("npx") is None:
        pytest.skip("npx is required for @modelcontextprotocol/server-filesystem")
    home, notes = tmp_path / "home", tmp_path / "notas"
    notes.mkdir()
    (notes / "compra.md").write_text("# Lista de la compra\n- pan\n- leche\n")
    agent = home / "agents" / "viernes"
    (agent / "tool").mkdir(parents=True)
    shutil.copy(REPO / "agents" / "viernes" / "agent.md", agent / "agent.md")
    server = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(notes)],
    }
    (agent / "tool" / "tool.json").write_text(json.dumps({"mcpServers": {"filesystem": server}}))
    request = TaskRequest(
        objetivo=f"Lista los ficheros de la carpeta {notes} y resume el contenido de cada nota."
    )
    deps = RunDeps(root=home, engine=ClaudeEngine(), task_id_factory=lambda: TASK_ID)

    result = await run_task("viernes", request, deps)

    log = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    events = [json.loads(line) for line in log.read_text().splitlines()]
    called = [event["tool"] for event in events if event["type"] == "tool_call"]
    assert any("list" in tool or "directory_tree" in tool for tool in called), called
    assert any("read" in tool for tool in called), called
    assert UNSTRUCTURED not in result.errores
    assert result.resumen
