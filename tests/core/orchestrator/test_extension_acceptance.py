"""Offline acceptance: three extensions in one running session, no Python edit, no restart."""

import asyncio
import json
import sys

import pytest
from typer.testing import CliRunner

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.skills_home import set_native, write_skill
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.changes import FakeChanges
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.servers import FAKE_FS_SERVER
from tony.apps.cli.main import create_app
from tony.core.orchestrator.runtime import CoreRuntime

NO_PIN = SHIPPED_POLICY_YAML.replace("pin_required: true", "pin_required: false")
NOTAS_RULE = '  - match: "notas.*"\n    verdict: allow\n    id: notas-allow\n'
DONE = {"resumen": "hecho", "datos": None, "pasos": [], "errores": []}


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


async def until(predicate, timeout=10.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_server_skill_and_rule_added_in_one_running_session(tmp_path):
    home, notes = make_tony_home(tmp_path, policy=NO_PIN)
    set_native(home, "viernes", ["read_skill"])
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Lee a.md"}), Say("Hecho")])
    worker = FakeModelEngine(
        [CallTool("notas.read_file", {"path": "a.md"}), Final(structured=DONE)]
    )
    events, changes = [], FakeChanges()
    runtime = CoreRuntime(
        home, events.append, chat_engine=chat, engine=worker, environ={}, changes=changes
    )
    serving = asyncio.create_task(runtime.serve())
    await until(lambda: any(e["type"] == "reply_mode" for e in events))

    result = CliRunner().invoke(
        create_app(),
        [
            "mcp", "add", "notas", sys.executable,
            "--arg", str(FAKE_FS_SERVER), "--arg", str(notes),
            "--agent", "viernes",
        ],
        env={"TONY_HOME": str(home)},
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    write_skill(home, "resumir", "Resume notas en tres viñetas")
    policy = home / "agents/edith/policy.yaml"
    policy.write_text(policy.read_text().replace("rules:\n", f"rules:\n{NOTAS_RULE}", 1))
    await changes.push(home / "agents/viernes/tool/tool.json", policy)

    runtime.submit({"type": "send_message", "text": "Lee a.md"})
    await until(lambda: any(e["type"] == "result" and e["scope"] == "turn" for e in events))
    runtime.submit({"type": "stop"})
    await asyncio.wait_for(serving, 5)

    assert "- resumir: Resume notas en tres viñetas" in worker.spec.system_prompt
    assert "notas.read_file" in worker.offered
    assert worker.replies[0].text == "# Nota A\nComprar pan."
    audit = [json.loads(line) for line in (home / "logs/audit.jsonl").read_text().splitlines()]
    assert [(line["tool"], line["verdict"], line["rule"]) for line in audit] == [
        ("notas.read_file", "allow", "notas-allow")
    ]
