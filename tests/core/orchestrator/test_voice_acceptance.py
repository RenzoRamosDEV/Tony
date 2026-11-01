"""Offline acceptance: a spoken request, Edith's question by voice and a spoken answer."""

import json

import pytest

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.test_runtime import DONE, Harness, home_for
from tests.core.orchestrator.tony_home import set_config
from tests.core.voice.service_harness import EDITH, FakeLoader, voice_threads
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.voice import ScriptedAudioInput, ScriptedStt, frames
from tony.core.voice.service import VoiceService

UTTERANCE = frames("..SSSSSS" + "." * 22)
SILENCE = frames("." * 10)
NO_PIN = SHIPPED_POLICY_YAML.replace("pin_required: true", "pin_required: false")
SPOKEN_QUESTION_END = "¿Autoriza?"


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def audit(home):
    lines = (home / "logs" / "audit.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


async def converse(tmp_path, answer_frames, answer_text, policy=NO_PIN):
    home, notes = home_for(tmp_path, policy)
    (notes / "viejo.md").write_text("viejo")
    set_config(home, "reply_mode: voice\n")
    loader = FakeLoader()
    loader.audio = ScriptedAudioInput(sessions=[UTTERANCE, answer_frames])
    loader.stt = ScriptedStt("Borra viejo.md", answer_text)
    voice = VoiceService(loader)
    chat = FakeChatEngine(
        [CallTool("tony.delegate", {"objetivo": "Borra viejo.md"}), Say("Listo, señor.")]
    )
    worker = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": "viejo.md"}), Final(structured=DONE)]
    )
    async with Harness(home, chat, worker, voice=voice) as harness:
        await harness.until(lambda: voice.ready)
        harness.send(type="listen")
        await harness.until(
            lambda: any(e.get("scope") == "turn" for e in harness.of("result")), timeout=10
        )
        assert voice.wait_silent(5)
    assert voice_threads() == set()
    return home, notes, harness, loader


def spoken_question(loader):
    return [(text, voice) for text, voice in loader.tts.calls if text.endswith(SPOKEN_QUESTION_END)]


async def test_yes_by_voice_runs_the_tool(tmp_path):
    home, notes, harness, loader = await converse(tmp_path, UTTERANCE, "Sí, Edith.")

    [transcript] = harness.of("transcript")
    assert transcript["text"] == "Borra viejo.md"
    assert harness.of("turn_started")[0]["origin"] == "voice"
    [(question, used)] = spoken_question(loader)
    assert used == EDITH and "Regla:" not in question
    assert not (notes / "viejo.md").exists()
    [line] = [a for a in audit(home) if a["tool"] == "filesystem.delete_file"]
    assert line["user_decision"] == "allow"
    assert "Listo, señor." in loader.output.played


async def test_anything_else_denies_and_cancels_the_task(tmp_path):
    home, notes, harness, _ = await converse(tmp_path, UTTERANCE, "vale")

    assert (notes / "viejo.md").exists()
    [line] = [a for a in audit(home) if a["tool"] == "filesystem.delete_file"]
    assert line["user_decision"] == "deny"
    [task] = [e for e in harness.of("result") if e["scope"] == "task"]
    assert task["outcome"] == "cancelled"
    assert len(harness.of("transcript")) == 1


async def test_silence_times_out_and_closes_the_microphone(tmp_path):
    policy = NO_PIN.replace("confirm_timeout_s: 60", "confirm_timeout_s: 1")
    home, notes, harness, loader = await converse(tmp_path, SILENCE, "nunca", policy)

    assert (notes / "viejo.md").exists()
    [line] = [a for a in audit(home) if a["tool"] == "filesystem.delete_file"]
    assert line["user_decision"] == "timeout"
    assert loader.audio.opened == 2 and loader.audio.closed == 2
    assert [e["state"] for e in harness.of("voice_state")][-1] == "ready"
