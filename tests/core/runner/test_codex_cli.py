"""`CodexCliRunner`: the `AgentRunner` for the `codex_cli` engine (`tony run`).

Driven against the fake `codex` binary (no network, no real Codex): each scripted
response becomes the structured output Codex would hand back on `--output-schema`.
Also proves the security policy from the task brief: the built command line never
carries `--dangerously-bypass-approvals-and-sandbox`/`--approve-for-me`, and always
carries `-s read-only`.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from tests.fakes.fake_codex import write_script
from tony.core.config import load_settings
from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner.cancel import CancelToken
from tony.core.runner.codex_cli import CodexCliRunner
from tony.core.runner.contracts import TaskRequest

FAKE_CODEX = [sys.executable, "-m", "tests.fakes.fake_codex"]


class RecordingEvents:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type, payload) -> None:
        self.events.append((event_type, payload))


class NeverGate:
    async def confirm(self, request):
        return False


async def no_call(qualified, args, timeout):
    raise AssertionError("no debería llamar a ninguna tool en estos tests")


def make_runner(script_path: Path, env: dict[str, str] | None = None) -> CodexCliRunner:
    settings = load_settings(None)
    return CodexCliRunner(
        settings=settings,
        task_id="t1",
        gate=NeverGate(),
        call=no_call,
        codex_command=[*FAKE_CODEX],
        env={"FAKE_CODEX_SCRIPT": str(script_path)},
        cancel_token=CancelToken(),
    )


def make_spec() -> AgentSpec:
    return AgentSpec(name="viernes", role="worker", model="claude-sonnet", path=Path("/tmp/x"))


async def test_run_parses_the_final_result_into_a_task_result(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [{"session_id": "s1", "result": {"status": "ok", "resumen": "hecho"}}],
    )
    runner = make_runner(script)

    result = await runner.run(
        make_spec(), TaskRequest(objetivo="haz algo"), ToolCatalog(), RecordingEvents()
    )

    assert result.status == "ok"
    assert result.resumen == "hecho"


async def test_run_returns_an_error_status_for_output_that_does_not_match_the_schema(
    tmp_path: Path,
) -> None:
    script = write_script(
        tmp_path / "script.json",
        [{"session_id": "s1", "result": {"status": "no-es-un-status-valido"}}],
    )
    runner = make_runner(script)

    result = await runner.run(
        make_spec(), TaskRequest(objetivo="haz algo"), ToolCatalog(), RecordingEvents()
    )

    assert result.status == "error"


async def test_the_built_command_never_bypasses_approvals_and_always_uses_read_only(
    tmp_path: Path,
) -> None:
    script = write_script(
        tmp_path / "script.json",
        [{"session_id": "s1", "result": {"status": "ok", "resumen": "hecho"}}],
    )
    runner = make_runner(script)
    captured: dict[str, list[str]] = {}
    original = runner._build_argv

    def spy(*args, **kwargs):
        argv = original(*args, **kwargs)
        captured["argv"] = argv
        return argv

    runner._build_argv = spy

    await runner.run(
        make_spec(), TaskRequest(objetivo="haz algo"), ToolCatalog(), RecordingEvents()
    )

    argv = captured["argv"]
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert "--approve-for-me" not in argv
    assert "-s" in argv and argv[argv.index("-s") + 1] == "read-only"


async def test_the_subprocess_never_inherits_this_process_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A codex that unexpectedly reads stdin must not hang the task on an inherited tty."""
    script = write_script(
        tmp_path / "script.json",
        [{"session_id": "s1", "result": {"status": "ok", "resumen": "hecho"}}],
    )
    runner = make_runner(script)
    captured: dict[str, object] = {}
    original = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        captured["stdin"] = kwargs.get("stdin")
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

    await runner.run(
        make_spec(), TaskRequest(objetivo="haz algo"), ToolCatalog(), RecordingEvents()
    )

    assert captured["stdin"] == asyncio.subprocess.DEVNULL
