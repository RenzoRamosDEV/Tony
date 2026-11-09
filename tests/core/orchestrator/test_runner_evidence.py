import json
from datetime import UTC, datetime

import pytest

from tests.core.orchestrator.skills_home import set_native, write_skill, write_subagent
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import ByAgentEngine, CallTool, FakeModelEngine, Final
from tests.fakes.guards import RecordingGuard
from tests.fakes.servers import fake_fs_entry
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.runner import RunDeps, run_task

TASK_ID = "a" * 32
REQUEST = TaskRequest(objetivo="Qué hay en a.md")
FIXED = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
READ = CallTool("filesystem.read_file", {"path": "a.md"})
SKILL = "Instrucciones secretas del procedimiento."


def source(excerpt, title="Nota A"):
    return {
        "connector": "filesystem",
        "id": "a.md",
        "title": title,
        "retrieved_at": "2026-11-01T09:00:00Z",
        "excerpt": excerpt,
    }


REAL = source("Comprar pan.")
INVENTED = source("Comprar vino.", title="Inventada")
DROPPED = (
    "fuente descartada: «Inventada» — el extracto no aparece en ningún resultado de herramienta"
)


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def result_with(*sources):
    return {"resumen": "ok", "datos": {"fuentes": list(sources)}, "pasos": ["leí"], "errores": []}


async def run(home, engine, published=None, guard=None):
    deps = RunDeps(
        root=home,
        guard=guard,
        engine=engine,
        environ={},
        task_id_factory=lambda: TASK_ID,
        clock=lambda: FIXED,
        publish=(published if published is not None else []).append,
    )
    return await run_task("viernes", REQUEST, deps)


def task_log(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_only_the_real_source_survives_with_a_warning(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    engine = FakeModelEngine([READ, Final(structured=result_with(REAL, INVENTED))])

    result = await run(home, engine)

    assert result.datos == {"fuentes": [REAL]}
    assert result.pasos == ["leí", DROPPED]
    assert result.errores == []


async def test_outcome_stays_ok_and_event_and_log_carry_the_validated_result(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    published = []
    engine = FakeModelEngine([READ, Final(structured=result_with(REAL, INVENTED))])

    result = await run(home, engine, published)

    [event] = [item for item in published if item["type"] == "result"]
    [finished] = [line for line in task_log(home) if line["type"] == "task_finished"]
    assert event["outcome"] == finished["outcome"] == "ok"
    assert event["result"] == result.model_dump()
    assert finished["result"] == result.model_dump()


async def test_result_without_fuentes_is_unchanged(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    plain = {"resumen": "ok", "datos": {"n": 1}, "pasos": ["a"], "errores": []}
    engine = FakeModelEngine([READ, Final(structured=plain)])

    result = await run(home, engine)

    assert result.model_dump() == plain


async def test_source_from_a_subagent_tool_result_is_kept_for_the_parent(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    set_native(home, "viernes", ["read_skill", "run_subagent"])
    write_subagent(home, "lector", servers={"filesystem": fake_fs_entry(str(notes))})
    call = CallTool("tony.run_subagent", {"name": "lector", "tarea": {"objetivo": "lee a.md"}})
    engine = ByAgentEngine(
        {
            "viernes": [call, Final(structured=result_with(REAL))],
            "lector": [READ, Final(structured={"resumen": "leído"})],
        }
    )

    result = await run(home, engine)

    assert result.datos == {"fuentes": [REAL]}
    assert result.pasos == ["leí"]


async def test_source_quoting_only_a_skill_body_is_dropped(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    set_native(home, "viernes", ["read_skill"])
    write_skill(home, "procedimiento", body=SKILL)
    quote = source("Instrucciones secretas del procedimiento.", title="Inventada")
    engine = FakeModelEngine(
        [
            CallTool("tony.read_skill", {"name": "procedimiento"}),
            Final(structured=result_with(quote)),
        ]
    )

    result = await run(home, engine)

    assert result.datos == {"fuentes": []}
    assert result.pasos == ["leí", DROPPED]


async def test_masked_secret_in_an_excerpt_still_matches(tmp_path):
    entry = fake_fs_entry(str(tmp_path), env={"TOKEN": "${GITHUB_TOKEN}"})
    home, _ = make_viernes_home(tmp_path, {"extra": entry})
    (home / "config").mkdir(exist_ok=True)
    (home / "config" / ".env").write_text("GITHUB_TOKEN=s3cr3t-value\n")
    echo = CallTool("extra.echo_env", {"name": "TOKEN"})
    engine = FakeModelEngine([echo, Final(structured=result_with(source("s3cr3t-value")))])

    result = await run(home, engine, guard=RecordingGuard())

    assert result.datos == {"fuentes": [source("***")]}
    assert result.pasos == ["leí"]
