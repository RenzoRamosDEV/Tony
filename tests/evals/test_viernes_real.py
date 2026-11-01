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
    shutil.copytree(REPO / "agents" / "edith", home / "agents" / "edith")
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


@pytest.mark.evals
@pytest.mark.timeout(300)
async def test_viernes_uses_a_skill_and_a_subagent_with_the_real_model(tmp_path):
    if shutil.which("npx") is None:
        pytest.skip("npx is required for @modelcontextprotocol/server-filesystem")
    home, notes = tmp_path / "home", tmp_path / "notas"
    notes.mkdir()
    (notes / "compra.md").write_text("# Lista de la compra\n- pan\n- leche\n")
    server = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(notes)],
    }
    agent = home / "agents" / "viernes"
    (agent / "tool").mkdir(parents=True)
    shutil.copy(REPO / "agents" / "viernes" / "agent.md", agent / "agent.md")
    (agent / "tool" / "tool.json").write_text(
        json.dumps({"mcpServers": {}, "native": ["read_skill", "run_subagent"]})
    )
    shutil.copytree(REPO / "agents" / "edith", home / "agents" / "edith")
    skill = agent / "skills" / "delegar-lectura"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: delegar-lectura\ndescription: Cómo leer notas\n---\n"
        "Para leer notas, usa siempre el subagente `lector` con tony.run_subagent.\n"
    )
    sub = agent / "subagents" / "lector"
    (sub / "tool").mkdir(parents=True)
    (sub / "agent.md").write_text(
        "---\nname: lector\nrole: worker\nmodel: claude-sonnet\n"
        "persona: {language: es, tone: directo}\nvoice: {tts: kokoro/em_alex}\n"
        "description: Lee notas de la carpeta de notas\n---\n"
        "Eres un lector de notas. Usa tus herramientas y responde con el resultado "
        "estructurado {resumen, datos, pasos, errores}.\n"
    )
    (sub / "tool" / "tool.json").write_text(json.dumps({"mcpServers": {"filesystem": server}}))
    request = TaskRequest(
        objetivo=(
            "Lee primero la skill delegar-lectura y síguela para resumir la nota "
            f"{notes / 'compra.md'}."
        )
    )
    deps = RunDeps(root=home, engine=ClaudeEngine(), task_id_factory=lambda: TASK_ID)

    result = await run_task("viernes", request, deps)

    audit = [json.loads(line) for line in (home / "logs" / "audit.jsonl").read_text().splitlines()]
    assert any(line["agent"] == "viernes/lector" for line in audit), audit
    assert UNSTRUCTURED not in result.errores
