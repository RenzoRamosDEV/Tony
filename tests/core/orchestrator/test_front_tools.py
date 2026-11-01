import asyncio
import json

import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.memory.preferences import PREFERENCES_FILE, PreferencesFile
from tony.core.orchestrator.front_tools import WAITING_PHRASE, FrontTools

RESULT = TaskResult(resumen="Hay 2 notas", datos=["a.md", "b.md"], pasos=["listar"])


class FakeGate:
    def __init__(self, unlocked=True) -> None:
        self.unlocked = unlocked
        self.checks = 0

    async def ensure_unlocked(self) -> bool:
        self.checks += 1
        return self.unlocked


class FakeWorker:
    def __init__(self, delay=0.0, result=RESULT) -> None:
        self.delay = delay
        self.result = result
        self.requests: list[TaskRequest] = []
        self.cancelled = False

    async def __call__(self, request: TaskRequest) -> TaskResult:
        self.requests.append(request)
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.result


def make(tmp_path, *, unlocked=True, delay=0.0, wait_s=0.05):
    published, gate, worker = [], FakeGate(unlocked), FakeWorker(delay)
    front = FrontTools(
        front_agent="jarvis",
        preferences=PreferencesFile(tmp_path, SecretMasker({"s3cr3t"})),
        gate=gate,
        run_worker=worker,
        publish=published.append,
        waiting_after_s=wait_s,
    )
    tools = {tool.id: tool for tool in front.tools()}
    return tools, published, gate, worker


def prefs_text(tmp_path):
    return (tmp_path / PREFERENCES_FILE).read_text()


def test_exactly_the_three_control_tools(tmp_path):
    tools, *_ = make(tmp_path)

    assert sorted(tools) == ["tony.delegate", "tony.remember", "tony.set_reply_mode"]
    assert tools["tony.delegate"].input_schema["required"] == ["objetivo"]
    assert tools["tony.remember"].input_schema["required"] == ["text"]
    assert tools["tony.set_reply_mode"].input_schema["properties"]["mode"]["enum"] == [
        "auto",
        "voice",
        "text",
        "both",
    ]


async def test_remember_appends_a_preference(tmp_path):
    tools, *_ = make(tmp_path)

    reply = await tools["tony.remember"].handler({"text": " uno\ndos s3cr3t "})

    assert not reply.is_error
    assert prefs_text(tmp_path) == "- uno dos ***\n"


@pytest.mark.parametrize("args", [{"text": "   "}, {}, {"text": 3}])
async def test_remember_rejects_empty_or_missing_text(tmp_path, args):
    tools, *_ = make(tmp_path)

    reply = await tools["tony.remember"].handler(args)

    assert reply.is_error
    assert not (tmp_path / PREFERENCES_FILE).exists()


async def test_set_reply_mode_persists_and_publishes(tmp_path):
    tools, published, *_ = make(tmp_path)

    reply = await tools["tony.set_reply_mode"].handler({"mode": "text"})

    assert not reply.is_error
    assert prefs_text(tmp_path) == "reply_mode: text\n"
    [event] = published
    assert (event["type"], event["mode"]) == ("reply_mode", "text")


@pytest.mark.parametrize("args", [{"mode": "loud"}, {}])
async def test_set_reply_mode_rejects_invalid_modes(tmp_path, args):
    tools, published, *_ = make(tmp_path)

    reply = await tools["tony.set_reply_mode"].handler(args)

    assert reply.is_error
    assert "auto, voice, text, both" in reply.text
    assert published == []
    assert not (tmp_path / PREFERENCES_FILE).exists()


async def test_delegate_returns_the_worker_result_unchanged(tmp_path):
    tools, published, _, worker = make(tmp_path)
    args = {"objetivo": "Lista mis notas", "contexto": "", "restricciones": []}

    reply = await tools["tony.delegate"].handler(args)

    assert not reply.is_error
    assert json.loads(reply.text) == RESULT.model_dump(mode="json")
    assert worker.requests == [TaskRequest(**args)]
    assert published == []


@pytest.mark.parametrize("args", [{"objetivo": ""}, {}, {"objetivo": "x", "restricciones": "no"}])
async def test_delegate_validation_error_creates_no_task(tmp_path, args):
    tools, _, gate, worker = make(tmp_path)

    reply = await tools["tony.delegate"].handler(args)

    assert reply.is_error
    assert worker.requests == [] and gate.checks == 0


async def test_delegate_empty_objective_message(tmp_path):
    tools, *_ = make(tmp_path)

    reply = await tools["tony.delegate"].handler({"objetivo": "  "})

    assert "objetivo must not be empty" in reply.text


async def test_delegate_refused_while_locked(tmp_path):
    tools, _, gate, worker = make(tmp_path, unlocked=False)

    reply = await tools["tony.delegate"].handler({"objetivo": "Lista"})

    assert json.loads(reply.text) == {"error": "locked"}
    assert worker.requests == [] and gate.checks == 1


async def test_waiting_phrase_once_when_the_worker_is_slow(tmp_path):
    tools, published, *_ = make(tmp_path, delay=0.2, wait_s=0.05)

    await tools["tony.delegate"].handler({"objetivo": "Lista"})

    [event] = published
    assert (event["type"], event["agent"], event["text"]) == ("progress", "jarvis", WAITING_PHRASE)
    assert WAITING_PHRASE == "Un momento, señor; estoy en ello."


async def test_no_waiting_phrase_when_the_worker_is_fast(tmp_path):
    tools, published, *_ = make(tmp_path, delay=0.0, wait_s=0.2)

    await tools["tony.delegate"].handler({"objetivo": "Lista"})

    assert published == []


def test_default_waiting_threshold_is_three_seconds(tmp_path):
    front = FrontTools(
        front_agent="jarvis",
        preferences=PreferencesFile(tmp_path),
        gate=FakeGate(),
        run_worker=FakeWorker(),
        publish=lambda event: None,
    )

    assert front.waiting_after_s == 3.0


async def test_cancelling_delegate_cancels_the_worker(tmp_path):
    tools, _, _, worker = make(tmp_path, delay=10)
    call = asyncio.create_task(tools["tony.delegate"].handler({"objetivo": "Lista"}))
    while not worker.requests:
        await asyncio.sleep(0.01)

    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    await asyncio.sleep(0)

    assert worker.cancelled
