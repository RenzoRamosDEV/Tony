"""Sanity check for the fake `codex` binary used to test the codex_cli engine (no network).

The fake emulates the handful of `codex exec`/`codex exec resume` invocations the
codex_cli engine (group 4) needs: a scripted sequence of JSON responses consumed one
per subprocess invocation, with `resume <session_id>` validated against the session id
of the previous response.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fakes.fake_codex import write_script

FAKE_CODEX = [sys.executable, "-m", "tests.fakes.fake_codex"]


def run_codex(script_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*FAKE_CODEX, *args],
        env={"FAKE_CODEX_SCRIPT": str(script_path)},
        capture_output=True,
        text=True,
    )


def test_exec_emits_the_first_scripted_response_as_a_json_line(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [{"session_id": "s1", "result": {"status": "ok", "resumen": "hecho"}}],
    )

    proc = run_codex(script, "exec", "--json", "--output-schema", "schema.json", "haz algo")

    assert proc.returncode == 0
    assert [json.loads(line) for line in proc.stdout.splitlines()] == [
        {"type": "thread.started", "thread_id": "s1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "agent_message",
                "text": json.dumps({"status": "ok", "resumen": "hecho"}),
            },
        },
        {"type": "turn.completed", "usage": {}},
    ]


def test_each_invocation_consumes_the_next_scripted_response(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [
            {"session_id": "s1", "result": {"status": "ok", "resumen": "primero"}},
            {"session_id": "s1", "result": {"status": "ok", "resumen": "segundo"}},
        ],
    )

    first = run_codex(script, "exec", "--json", "--output-schema", "schema.json", "uno")
    second = run_codex(
        script, "exec", "resume", "s1", "--json", "--output-schema", "schema.json", "dos"
    )

    assert (
        json.loads(json.loads(first.stdout.splitlines()[2])["item"]["text"])["resumen"] == "primero"
    )
    assert (
        json.loads(json.loads(second.stdout.splitlines()[2])["item"]["text"])["resumen"]
        == "segundo"
    )


def test_resume_with_the_wrong_session_id_fails_without_consuming_the_script(
    tmp_path: Path,
) -> None:
    script = write_script(
        tmp_path / "script.json",
        [{"session_id": "s1", "result": {"status": "ok", "resumen": "primero"}}],
    )

    proc = run_codex(script, "exec", "resume", "otra-sesion", "--json", "uno")

    assert proc.returncode != 0
    assert "otra-sesion" in proc.stderr


def test_malformed_response_is_emitted_verbatim_for_schema_violation_tests(
    tmp_path: Path,
) -> None:
    script = write_script(
        tmp_path / "script.json", [{"session_id": "s1", "result": {"campo_inesperado": True}}]
    )

    proc = run_codex(script, "exec", "--json", "uno")

    assert proc.returncode == 0
    assert json.loads(json.loads(proc.stdout.splitlines()[2])["item"]["text"]) == {
        "campo_inesperado": True
    }


def test_exhausted_script_fails_clearly(tmp_path: Path) -> None:
    script = write_script(tmp_path / "script.json", [])

    proc = run_codex(script, "exec", "uno")

    assert proc.returncode != 0
    assert "guion" in proc.stderr or "script" in proc.stderr


@pytest.mark.parametrize(
    "agent_text", ["tool requires approval", "not JSON", '{"display_text": "hola"}']
)
def test_agent_text_is_emitted_literally(tmp_path: Path, agent_text: str) -> None:
    script = write_script(
        tmp_path / "script.json",
        [
            {
                "session_id": "s1",
                "agent_text": agent_text,
                "result": {"ignored": True},
            }
        ],
    )
    proc = run_codex(script, "exec", "--json", "uno")
    assert proc.returncode == 0
    assert json.loads(proc.stdout.splitlines()[2])["item"]["text"] == agent_text
