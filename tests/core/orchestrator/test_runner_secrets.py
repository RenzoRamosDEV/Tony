import json

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.servers import fake_fs_entry
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.runner import RunDeps, run_task

TASK_ID = "5" * 32
REQUEST = TaskRequest(objetivo="Lee mis notas")
OK = {"resumen": "ok", "datos": None, "pasos": [], "errores": []}


def write_env(home, text):
    (home / "config").mkdir(exist_ok=True)
    (home / "config" / ".env").write_text(text)


async def run(home, steps, environ):
    engine = FakeModelEngine([*steps, Final(structured=OK)])
    deps = RunDeps(root=home, engine=engine, environ=environ, task_id_factory=lambda: TASK_ID)
    await run_task("viernes", REQUEST, deps)
    log = (home / "logs" / "tasks" / f"{TASK_ID}.jsonl").read_text()
    return engine.replies, log, [json.loads(line) for line in log.splitlines()]


def results_of(events):
    return [event["content"] for event in events if event["type"] == "tool_result"]


async def test_home_placeholder_is_resolved_but_not_masked(tmp_path):
    entry = fake_fs_entry("${HOME}/notas", env={"NOTES": "${HOME}/notas"})
    home, _ = make_viernes_home(tmp_path, {"extra": entry})

    replies, _, events = await run(
        home,
        [CallTool("extra.list_directory", {}), CallTool("extra.echo_env", {"name": "NOTES"})],
        environ={"HOME": str(tmp_path)},
    )

    assert [reply.text for reply in replies] == ["a.md", f"{tmp_path}/notas"]
    assert results_of(events) == ["a.md", f"{tmp_path}/notas"]


async def test_env_file_secret_used_by_a_server_is_masked(tmp_path):
    entry = fake_fs_entry("${HOME}/notas", env={"TOKEN": "${GITHUB_TOKEN}"})
    home, _ = make_viernes_home(tmp_path, {"extra": entry})
    write_env(home, "GITHUB_TOKEN=s3cr3t\n")

    replies, log, events = await run(
        home, [CallTool("extra.echo_env", {"name": "TOKEN"})], environ={"HOME": str(tmp_path)}
    )

    assert replies[0].text == "***"
    assert results_of(events) == ["***"]
    assert "s3cr3t" not in log


async def test_secret_looking_process_variable_is_masked(tmp_path):
    home, _ = make_viernes_home(
        tmp_path, {"extra": fake_fs_entry(str(tmp_path), env={"K": "${API_KEY}"})}
    )

    replies, log, _ = await run(
        home, [CallTool("extra.echo_env", {"name": "K"})], environ={"API_KEY": "k3y"}
    )

    assert replies[0].text == "***"
    assert "k3y" not in log


async def test_env_file_value_unused_by_any_server_is_still_masked(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    (notes / "b.md").write_text("clave s3cr3t")
    write_env(home, "GITHUB_TOKEN=s3cr3t\n")

    replies, log, _ = await run(
        home, [CallTool("filesystem.read_file", {"path": "b.md"})], environ={}
    )

    assert replies[0].text == "clave ***"
    assert "s3cr3t" not in log
