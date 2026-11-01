import asyncio

import pytest

from tests.fakes.fake_chat import Fail, FakeChatEngine, Say, Wait
from tests.fakes.fake_engine import CallTool, ScriptError
from tony.core.orchestrator.ports import ChatOutcome, ProxiedTool, ToolReply, Usage


def tool(tool_id, log):
    async def handler(args):
        log.append(args)
        return ToolReply(text=f"r{args}")

    return ProxiedTool(id=tool_id, description="d", input_schema={}, handler=handler)


async def converse(engine, tools=(), chunks=None):
    chunks = [] if chunks is None else chunks
    return await engine.converse(None, "S", "P", list(tools), "m", chunks.append)


async def test_streams_chunks_and_returns_the_joined_text():
    chunks = []
    engine = FakeChatEngine([Say("Buenas", " tardes")], usage=Usage(1, 1))

    outcome = await converse(engine, chunks=chunks)

    assert chunks == ["Buenas", " tardes"]
    assert outcome == ChatOutcome(text="Buenas tardes", usage=[Usage(1, 1)])
    assert (engine.system_prompts, engine.prompts, engine.model_ids) == (["S"], ["P"], ["m"])


async def test_calls_offered_tools_and_records_replies():
    log = []
    engine = FakeChatEngine([CallTool("tony.remember", {"text": "x"}), Say("hecho")])

    await converse(engine, [tool("tony.remember", log)])

    assert log == [{"text": "x"}]
    assert engine.replies == [ToolReply(text="r{'text': 'x'}")]
    assert engine.offered == [["tony.remember"]]


async def test_unoffered_tool_fails_clearly():
    with pytest.raises(ScriptError, match="tony.delegate"):
        await converse(FakeChatEngine([CallTool("tony.delegate")]))


async def test_fail_raises_and_later_turns_continue():
    engine = FakeChatEngine([Fail()], [Say("bien")])

    with pytest.raises(RuntimeError, match="model down"):
        await converse(engine)
    assert (await converse(engine)).text == "bien"
    assert (await converse(engine)).text == "ok"


async def test_wait_blocks_until_set():
    release = asyncio.Event()
    engine = FakeChatEngine([Wait(release), Say("fin")])
    turn = asyncio.create_task(converse(engine))
    await asyncio.sleep(0.01)

    assert not turn.done()
    release.set()
    assert (await turn).text == "fin"


async def test_wait_without_event_never_returns():
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(converse(FakeChatEngine([Wait()])), 0.05)
