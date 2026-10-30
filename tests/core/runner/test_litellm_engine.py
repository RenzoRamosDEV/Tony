"""Offline contract tests for both LiteLLM adapters."""

import asyncio
import json
from pathlib import Path

import pytest

from tests.fakes.fake_litellm import FakeCompletion, response, tool_call
from tony.core.config import EngineProfile, load_settings
from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCallOutcome, ToolCatalog, ToolRef
from tony.core.runner.cancel import CancelToken
from tony.core.runner.contracts import TaskRequest, TaskResult
from tony.core.runner.litellm_engine import (
    LiteLlmConversation,
    LiteLlmRunner,
    litellm_runner_factory,
)
from tony.core.runner.reply_mode import FrontReply
from tony.core.runner.strict_schema import strict_schema


class Events:
    def __init__(self):
        self.items = []

    def emit(self, name, payload):
        self.items.append((name, payload))


class Gate:
    def __init__(self):
        self.requests = []

    async def confirm(self, request):
        self.requests.append(request)
        return False


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")


def settings():
    return load_settings(None).model_copy(
        update={"engines": {"test": EngineProfile(type="litellm", model="gpt-4o")}}
    )


def spec(max_steps=3):
    return AgentSpec(
        name="test",
        role="worker",
        model="claude-sonnet",
        engine="test",
        path=Path("/tmp/test"),
        system_prompt="System",
        max_steps=max_steps,
    )


def catalog(confirm=False, names=("fs.read",)):
    return ToolCatalog.from_refs(
        ToolRef(
            "fs",
            name,
            name,
            "Read a file",
            {"type": "object", "properties": {"path": {"type": "string"}}},
            False,
            confirm,
        )
        for name in names
    )


async def no_call(*args):
    raise AssertionError("Unexpected tool execution")


def runner(fake, gate=None, call=no_call, token=None):
    return LiteLlmRunner(
        settings(), "t1", gate or Gate(), call, completion=fake, cancel_token=token
    )


async def run(fake, **kwargs):
    return await runner(fake, **kwargs).run(
        spec(), TaskRequest(objetivo="Goal"), ToolCatalog(), Events()
    )


async def test_direct_reply_and_request_contract():
    fake = FakeCompletion(response('{"status":"ok","resumen":"Done"}'))
    events = Events()
    result = await runner(fake).run(
        spec(1),
        TaskRequest(objetivo="Goal", contexto="Context", restricciones=["Constraint"]),
        ToolCatalog(),
        events,
    )
    assert result.status == "ok"
    assert result.resumen == "Done"
    sent = fake.calls[0]
    assert sent["model"] == "gpt-4o"
    assert "api_key" not in sent
    assert sent["messages"][0]["content"].startswith("System")
    assert all(
        value in sent["messages"][1]["content"] for value in ["Goal", "Context", "Constraint"]
    )
    assert sent["response_format"]["json_schema"] == {
        "name": "TaskResult",
        "strict": True,
        "schema": strict_schema(TaskResult),
    }
    assert [name for name, _ in events.items] == ["task.started", "task.finished"]


@pytest.mark.parametrize("denied", [False, True])
async def test_tool_dispatch_uses_barrier(denied):
    fake = FakeCompletion(
        response(tool_calls=[tool_call()]), response('{"status":"ok","resumen":"Done"}')
    )
    calls = []

    async def call(*args):
        calls.append(args)
        return ToolCallOutcome(ok=True, content="file content")

    gate, events = Gate(), Events()
    result = await runner(fake, gate, call).run(
        spec(), TaskRequest(objetivo="Read"), catalog(denied), events
    )
    assert result.status == ("cancelled" if denied else "ok")
    assert len(calls) == (0 if denied else 1)
    assert len(gate.requests) == int(denied)
    assert [name for name, _ in events.items] == [
        "task.started",
        "tool.call",
        "tool.result",
        "task.finished",
    ]
    assert events.items[2][1]["ok"] is not denied
    if not denied:
        assert calls[0][:2] == ("fs.read", {"path": "a"})
        assert fake.calls[1]["messages"][-1] == {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": "file content",
        }
        assert fake.calls[0]["tools"][0]["function"] == {
            "name": "fs_read",
            "description": "Read a file",
            "parameters": catalog().refs[0].input_schema,
        }


async def test_max_steps_stops_after_exact_limit():
    fake = FakeCompletion(*(response(tool_calls=[tool_call()]) for _ in range(2)))

    async def call(*args):
        return ToolCallOutcome(ok=True, content="ok")

    result = await runner(fake, call=call).run(
        spec(2), TaskRequest(objetivo="Read"), catalog(), Events()
    )
    assert result.status == "error"
    assert "2" in result.errores[0] and "límite" in result.errores[0]
    assert len(fake.calls) == 2
    assert len(result.pasos) == 2


@pytest.mark.parametrize(
    "content,status,summary",
    [
        ("Plain answer", "partial", "Plain answer"),
        ('```json\n{"status":"ok","resumen":"Extracted"}\n```', "ok", "Extracted"),
        ('{"status":"invalid","resumen":"bad"}', "error", None),
    ],
)
async def test_output_partitions(content, status, summary):
    result = await run(FakeCompletion(response(content)))
    assert result.status == status
    if summary is not None:
        assert result.resumen == summary


@pytest.mark.parametrize(
    "model,key",
    [
        ("gpt-4o", "OPENAI_API_KEY"),
        ("gemini/gemini-2.0-flash", "GEMINI_API_KEY"),
        ("anthropic/claude-sonnet-4-5", "ANTHROPIC_API_KEY"),
    ],
)
async def test_missing_credentials_fail_before_completion(monkeypatch, model, key):
    monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    fake = FakeCompletion()
    instance = runner(fake)
    instance._settings.engines["test"].model = model
    result = await instance.run(spec(), TaskRequest(objetivo="Goal"), ToolCatalog(), Events())
    assert result.status == "error"
    assert key in result.errores[0]
    assert fake.calls == []


async def test_unsupported_response_format_retries_without_it():
    from litellm.exceptions import UnsupportedParamsError

    fake = FakeCompletion(
        UnsupportedParamsError(
            message="response_format unsupported", model="gpt-4o", llm_provider="openai"
        ),
        response('{"status":"ok","resumen":"Recovered"}'),
    )
    result = await run(fake)
    assert result.status == "ok"
    assert "response_format" not in fake.calls[1]
    assert fake.calls[0]["messages"] == fake.calls[1]["messages"]


async def test_provider_error_is_not_retried():
    fake = FakeCompletion(RuntimeError("failure"))
    result = await run(fake)
    assert result.status == "error"
    assert len(fake.calls) == 1


async def test_conversation_keeps_history_and_delivers_callbacks_once():
    fake = FakeCompletion(
        response(json.dumps({"display_text": "Display", "speech_text": "Voice"})), response("Plain")
    )
    conversation = LiteLlmConversation(settings(), Gate(), no_call, completion=fake)
    await conversation.open(spec(), ToolCatalog(), None, Events())
    session = conversation.session_id
    texts, speeches = [], []

    async def on_text(text):
        texts.append(text)

    async def on_speech(text):
        speeches.append(text)

    first = await conversation.turn("First", on_text, on_speech)
    second = await conversation.turn("Second", on_text, on_speech)
    assert session and conversation.session_id == session
    assert first.structured == {"display_text": "Display", "speech_text": "Voice"}
    assert second.text == "Plain" and second.structured is None
    assert texts == ["Display", "Plain"] and speeches == ["Voice", "Plain"]
    assert [m["role"] for m in fake.calls[1]["messages"]] == ["system", "user", "assistant", "user"]
    assert fake.calls[0]["response_format"]["json_schema"]["schema"] == strict_schema(FrontReply)
    await conversation.close()
    assert conversation.session_id is None


@pytest.mark.parametrize("denied", [False, True])
async def test_conversation_tool_limit_or_denial(denied):
    fake = FakeCompletion(response(tool_calls=[tool_call()]))

    async def call(*args):
        return ToolCallOutcome(ok=True, content="ok")

    conversation = LiteLlmConversation(settings(), Gate(), call, completion=fake)
    await conversation.open(spec(1), catalog(denied), None, Events())
    result = await conversation.turn("Read")
    assert result.error
    assert ("confirm" if denied else "límite") in result.error


async def test_interrupt_stops_pending_completion_and_next_turn_works():
    entered = asyncio.Event()

    async def completion(**kwargs):
        if not entered.is_set():
            entered.set()
            await asyncio.Event().wait()
        return response('{"display_text":"Recovered"}')

    conversation = LiteLlmConversation(settings(), Gate(), no_call, completion=completion)
    await conversation.open(spec(), ToolCatalog(), None, Events())
    pending = asyncio.create_task(conversation.turn("Wait"))
    await entered.wait()
    await conversation.interrupt()
    result = await asyncio.wait_for(pending, 1)
    assert result.error
    assert (await conversation.turn("Retry")).text == "Recovered"


def test_factory_constructs_runner():
    token = CancelToken()
    instance = litellm_runner_factory(settings(), "t1", Gate(), no_call, token, None)
    assert isinstance(instance, LiteLlmRunner)
    assert instance._cancel_token is token


async def test_sanitized_names_do_not_collide_and_dispatch_multiple_tools():
    fake = FakeCompletion(
        response(
            tool_calls=[tool_call("fs_read", call_id="one"), tool_call("fs_read_1", call_id="two")]
        ),
        response('{"display_text":"Done"}'),
    )
    calls = []

    async def call(name, args, timeout):
        calls.append(name)
        return ToolCallOutcome(ok=True, content=name)

    conversation = LiteLlmConversation(settings(), Gate(), call, completion=fake)
    await conversation.open(spec(), catalog(names=("fs.read", "fs_read")), None, Events())
    result = await conversation.turn("Read both")
    assert result.text == "Done" and result.error is None
    assert calls == ["fs.read", "fs_read"]
    messages = fake.calls[1]["messages"]
    assert messages[-2]["tool_call_id"] == "one"
    assert messages[-1]["tool_call_id"] == "two"
    assert messages[-3]["tool_calls"][1]["function"]["name"] == "fs_read_1"
    assert result.usage == {"input_tokens": 4, "output_tokens": 6}


@pytest.mark.parametrize("name,args", [("unknown", "{}"), ("fs_read", "broken"), ("fs_read", "[]")])
async def test_invalid_tool_call_returns_feedback_without_execution(name, args):
    fake = FakeCompletion(
        response(tool_calls=[tool_call(name, args)]),
        response('{"status":"ok","resumen":"Recovered"}'),
    )
    result = await runner(fake).run(spec(), TaskRequest(objetivo="Read"), catalog(), Events())
    assert result.status == "ok"
    assert "inválidos" in fake.calls[1]["messages"][-1]["content"]


async def test_pre_cancelled_worker_never_calls_provider():
    token = CancelToken()
    token.cancel("user")
    fake = FakeCompletion()
    result = await run(fake, token=token)
    assert result.status == "cancelled"
    assert fake.calls == []


async def test_close_during_completion_finishes_turn_cleanly():
    entered = asyncio.Event()

    async def completion(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    conversation = LiteLlmConversation(settings(), Gate(), no_call, completion=completion)
    await conversation.open(spec(), ToolCatalog(), None, Events())
    pending = asyncio.create_task(conversation.turn("Wait"))
    await entered.wait()
    await conversation.close()
    result = await asyncio.wait_for(pending, 1)
    assert result.error
    assert conversation.session_id is None
    with pytest.raises(RuntimeError, match="no está abierta"):
        await conversation.turn("Closed")
