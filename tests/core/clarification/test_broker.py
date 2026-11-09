import asyncio

import pytest

from tony.core.clarification.broker import ClarificationBroker
from tony.core.clarification.port import Clarifier, NoChannelClarifier
from tony.core.clarification.request import ClarificationRequest


def request(request_id="r1", question="¿Qué cuenta?", options=("a", "b")):
    return ClarificationRequest(
        request_id=request_id,
        task_id="t1",
        agent="viernes",
        question=question,
        options=list(options),
    )


async def settle():
    for _ in range(3):
        await asyncio.sleep(0)


def make():
    published = []
    return ClarificationBroker(published.append), published


async def test_publishes_one_clarification_requested_with_all_fields():
    broker, published = make()
    asking = asyncio.create_task(broker.ask(request()))
    await settle()

    [event] = published
    assert {key: event[key] for key in event if key != "ts"} == {
        "type": "clarification_requested",
        "request_id": "r1",
        "task_id": "t1",
        "agent": "viernes",
        "question": "¿Qué cuenta?",
        "options": ["a", "b"],
    }
    broker.cancel()
    await asking


async def test_matching_answer_resolves_the_ask():
    broker, _ = make()
    asking = asyncio.create_task(broker.ask(request()))
    await settle()

    broker.answer("r1", "la personal")

    assert await asking == "la personal"


async def test_unknown_id_is_ignored_and_the_ask_stays_pending():
    broker, _ = make()
    asking = asyncio.create_task(broker.ask(request()))
    await settle()

    broker.answer("otro", "x")
    await settle()

    assert not asking.done()
    broker.answer("r1", "ok")
    assert await asking == "ok"


def test_answer_without_pending_is_ignored():
    broker, _ = make()

    broker.answer("r1", "x")


async def test_second_answer_for_the_same_request_is_ignored():
    broker, _ = make()
    asking = asyncio.create_task(broker.ask(request()))
    await settle()

    broker.answer("r1", "primera")
    broker.answer("r1", "segunda")

    assert await asking == "primera"


async def test_cancel_resolves_the_pending_ask_with_none():
    broker, _ = make()
    asking = asyncio.create_task(broker.ask(request()))
    await settle()

    broker.cancel()

    assert await asking is None


def test_cancel_without_pending_is_harmless():
    broker, _ = make()

    broker.cancel()


async def test_late_answer_after_cancel_is_ignored_by_the_next_ask():
    broker, _ = make()
    first = asyncio.create_task(broker.ask(request("r1")))
    await settle()
    broker.cancel()
    await first

    second = asyncio.create_task(broker.ask(request("r2")))
    await settle()
    broker.answer("r1", "tarde")
    await settle()

    assert not second.done()
    broker.answer("r2", "a tiempo")
    assert await second == "a tiempo"


async def test_timed_out_ask_clears_the_pending_so_a_late_answer_is_dropped():
    broker, _ = make()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(broker.ask(request()), 0.01)

    broker.answer("r1", "tarde")


async def test_second_ask_waits_for_the_first_one():
    broker, published = make()
    first = asyncio.create_task(broker.ask(request("r1")))
    second = asyncio.create_task(broker.ask(request("r2")))
    await settle()

    assert [event["request_id"] for event in published] == ["r1"]
    broker.answer("r1", "uno")
    await settle()
    assert [event["request_id"] for event in published] == ["r1", "r2"]
    broker.answer("r2", "dos")

    assert (await first, await second) == ("uno", "dos")


async def test_never_publishes_a_confirmation_event():
    broker, published = make()
    asking = asyncio.create_task(broker.ask(request()))
    await settle()
    broker.answer("r1", "x")
    await asking

    assert {event["type"] for event in published} == {"clarification_requested"}


async def test_no_channel_clarifier_returns_none_and_brokers_satisfy_the_protocol():
    assert await NoChannelClarifier().ask(request()) is None
    assert isinstance(NoChannelClarifier(), Clarifier)
    assert isinstance(make()[0], Clarifier)
