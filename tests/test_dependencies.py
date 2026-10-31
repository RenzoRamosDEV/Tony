"""Declared dependency ranges must match the APIs the code relies on."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_mcp_requirement_pins_the_2x_api() -> None:
    dependencies = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]

    assert "mcp>=2.3,<3" in dependencies


def test_web_extra_declares_fastapi_uvicorn_and_websockets() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    web = project["project"]["optional-dependencies"]["web"]
    dev = project["dependency-groups"]["dev"]

    names = {requirement.split(">=")[0].split("[")[0] for requirement in web}
    assert names == {"fastapi", "uvicorn", "websockets"}
    assert any(requirement.startswith("httpx>=") for requirement in dev)


def test_voice_extra_declares_the_engines_and_their_audio_stack() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    voice = project["project"]["optional-dependencies"]["voice"]

    for requirement in (
        "faster-whisper>=1.2,<2",
        "kokoro>=0.9.4,<1",
        "piper-tts>=1.8,<2",
        "silero-vad>=6,<7",
    ):
        assert requirement in voice
    names = {requirement.split(">=")[0].split("[")[0] for requirement in voice}
    assert {"onnxruntime", "numpy", "soundfile"} <= names


def test_voice_marker_is_declared_and_excluded_by_default() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    pytest_options = project["tool"]["pytest"]["ini_options"]

    assert any(marker.startswith("voice:") for marker in pytest_options["markers"])
    assert "not voice" in pytest_options["addopts"]


def test_torch_is_pinned_to_the_cpu_index() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    indexes = {index["name"]: index for index in project["tool"]["uv"]["index"]}

    assert indexes["pytorch-cpu"]["url"] == "https://download.pytorch.org/whl/cpu"
    assert indexes["pytorch-cpu"]["explicit"] is True
    assert project["tool"]["uv"]["sources"]["torch"] == [{"index": "pytorch-cpu"}]
