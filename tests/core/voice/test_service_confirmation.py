import pytest

from tests.core.voice.service_harness import EDITH, FakeLoader, Harness, voice_threads
from tests.fakes.voice import RecordingAudioOutput, ScriptedAudioInput, ScriptedStt, frames
from tony.core.events import core_events as ev
from tony.core.events.messages import Ruling, TaskResult

UTTERANCE = frames("..SSSS" + "." * 22)
QUESTION = (
    "Acción: borrar el archivo /home/renzo/notas/viejo.md. "
    "Regla: filesystem.delete*/confirm. ¿Autoriza?"
)
SPOKEN = "Acción: borrar el archivo /home/renzo/notas/viejo.md. ¿Autoriza?"


def pending(task_id="t1"):
    return ev.needs_confirmation(task_id, "filesystem.delete_file", "{}", QUESTION, True)


@pytest.fixture
async def harness():
    made = []

    def build(answer="Sí, Edith.", frames_=UTTERANCE, blocking=False):
        loader = FakeLoader()
        loader.audio = ScriptedAudioInput(frames_)
        loader.stt = ScriptedStt(answer)
        loader.output = RecordingAudioOutput(blocking=blocking)
        h = Harness(loader)
        made.append(h)
        return h

    yield build
    for h in made:
        h.service.close()
    assert voice_threads() == set()


async def started(h):
    h.start()
    await h.ready()
    return h


async def test_question_spoken_with_the_guard_voice_after_queued_sentences(harness):
    h = await started(harness(blocking=True))
    h.speaking_turn()
    h.observe(ev.token("jarvis", "Voy a ello. "), pending())
    assert h.loader.output.started.wait(5)
    assert h.loader.audio.opened == 0
    h.loader.output.release()
    await h.until(lambda: len(h.loader.output.played) == 2)
    assert h.loader.output.played == ["Voy a ello.", SPOKEN]
    assert h.loader.tts.calls[1] == (SPOKEN, EDITH)
    assert h.loader.audio.opened == 0
    h.loader.output.release()
    await h.until(lambda: h.loader.audio.opened == 1)


@pytest.mark.parametrize(("answer", "decision"), [("Sí, Edith.", "allow"), ("vale", "deny")])
async def test_spoken_answer_becomes_a_confirm_command(harness, answer, decision):
    h = await started(harness(answer))
    h.speaking_turn()
    h.observe(pending())
    await h.until(lambda: h.commands)
    assert h.commands == [{"type": "confirm", "task_id": "t1", "decision": decision}]
    assert h.of_type("transcript") == []
    await h.until(lambda: h.states()[-1] == ("ready", None))


async def test_confirmation_session_has_no_idle_timeout(harness):
    h = harness(frames_=frames("." * 400))
    h.service = type(h.service)(h.loader, idle_timeout_s=0)
    await started(h)
    h.speaking_turn()
    h.observe(pending())
    await h.until(lambda: h.loader.audio.opened == 1)
    assert h.states()[-1] == ("listening", None)


@pytest.mark.parametrize(
    "resolution",
    [
        ev.tool_call(
            "t1",
            "viernes",
            "filesystem.delete_file",
            "{}",
            Ruling(verdict="confirm", rule="r", user_decision="allow"),
        ),
        ev.task_result(
            "t1",
            "viernes",
            "cancelled",
            TaskResult(resumen="r"),
            input_tokens=0,
            output_tokens=0,
            elapsed_ms=0,
        ),
    ],
)
async def test_the_task_resolving_closes_the_session(harness, resolution):
    h = await started(harness(frames_=frames("...")))
    h.speaking_turn()
    h.observe(pending())
    await h.until(lambda: h.loader.audio.opened == 1)
    h.observe(resolution)
    await h.until(lambda: h.states()[-1] == ("ready", None))
    assert h.loader.audio.closed == 1 and h.commands == []


async def test_other_task_events_keep_the_session(harness):
    h = await started(harness(frames_=frames("...")))
    h.speaking_turn()
    h.observe(pending())
    await h.until(lambda: h.loader.audio.opened == 1)
    h.observe(ev.tool_call("t2", "viernes", "x", "{}", Ruling(verdict="allow", rule="r")))
    assert h.states()[-1] == ("listening", None)


async def test_banner_answer_first_makes_a_later_transcript_a_normal_turn(harness):
    h = await started(harness("¿Qué hora es?", frames_=frames("...")))
    h.speaking_turn()
    h.observe(pending())
    await h.until(lambda: h.loader.audio.opened == 1)
    h.observe(
        ev.tool_call(
            "t1", "viernes", "d", "{}", Ruling(verdict="confirm", rule="r", user_decision="allow")
        )
    )
    await h.until(lambda: h.states()[-1] == ("ready", None))
    h.loader.audio._frames = UTTERANCE
    h.service.listen()
    await h.until(lambda: h.commands)
    assert h.commands[0]["type"] == "send_message"


async def test_non_speaking_turn_does_not_speak_or_open_the_microphone(harness):
    h = await started(harness())
    h.speaking_turn(speaks=False)
    h.observe(pending())
    assert h.service.wait_silent(1)
    assert h.loader.tts.calls == [] and h.loader.audio.opened == 0


async def test_user_listen_while_armed_answers_the_confirmation(harness):
    h = await started(harness(blocking=True))
    h.speaking_turn()
    h.observe(pending())
    assert h.loader.output.started.wait(5)
    h.service.listen()
    await h.until(lambda: h.commands)
    assert h.commands == [{"type": "confirm", "task_id": "t1", "decision": "allow"}]
    assert h.loader.audio.opened == 1


async def test_turn_end_does_not_disarm_a_pending_confirmation(harness):
    h = await started(harness(blocking=True))
    h.speaking_turn()
    h.observe(pending())
    assert h.loader.output.started.wait(5)
    h.observe(ev.turn_result("jarvis", "", "voice"))
    h.loader.output.release()
    await h.until(lambda: h.commands)
    assert h.commands[0]["type"] == "confirm"


async def test_the_reply_after_a_spoken_answer_is_still_spoken(harness):
    h = await started(harness())
    h.speaking_turn()
    h.observe(pending())
    await h.until(lambda: h.commands)
    h.observe(ev.token("jarvis", "Hecho, señor."), ev.turn_result("jarvis", "x", "voice"))
    await h.until(lambda: h.loader.output.played[-1:] == ["Hecho, señor."])
