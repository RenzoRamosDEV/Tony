import asyncio
import io
import queue

import pytest

from tony.core.clarification.cli import CliClarifier, parse_answer
from tony.core.clarification.request import ClarificationRequest
from tony.core.guard.confirm import ConsoleLines

OPTIONS = ["Personal", "Trabajo"]


@pytest.mark.parametrize(
    ("line", "options", "answer"),
    [
        (None, OPTIONS, None),
        ("", OPTIONS, None),
        ("   ", OPTIONS, None),
        ("1", OPTIONS, "Personal"),
        ("2", OPTIONS, "Trabajo"),
        (" 2 ", OPTIONS, "Trabajo"),
        ("0", OPTIONS, "0"),
        ("3", OPTIONS, "3"),
        ("7", OPTIONS, "7"),
        ("-1", OPTIONS, "-1"),
        ("la de casa", OPTIONS, "la de casa"),
        ("  la de casa  ", OPTIONS, "la de casa"),
        ("1", [], "1"),
        ("hola", [], "hola"),
    ],
)
def test_parse_answer_partitions(line, options, answer):
    assert parse_answer(line, options) == answer


def request(options=OPTIONS):
    return ClarificationRequest(
        request_id="r1", task_id="t1", agent="viernes", question="¿Qué cuenta?", options=options
    )


async def ask_with(line, options=OPTIONS):
    err = io.StringIO()

    async def read_line():
        return line

    answer = await CliClarifier(read_line, err=err).ask(request(options))
    return answer, err.getvalue()


async def test_prints_agent_question_and_numbered_options_on_stderr():
    _, err = await ask_with("1")

    assert err == "Viernes: ¿Qué cuenta?\n1) Personal\n2) Trabajo\n"


async def test_question_without_options_prints_only_the_question():
    _, err = await ask_with("x", [])

    assert err == "Viernes: ¿Qué cuenta?\n"


async def test_returns_the_parsed_answer():
    assert (await ask_with("2"))[0] == "Trabajo"
    assert (await ask_with("texto libre"))[0] == "texto libre"
    assert (await ask_with(None))[0] is None


async def test_question_goes_to_stderr_not_stdout(capsys):
    await ask_with("1")

    assert capsys.readouterr().out == ""


async def test_line_typed_after_a_timeout_stays_queued_for_the_next_reader():
    feed: queue.Queue[str | None] = queue.Queue()
    console = ConsoleLines(iter(feed.get, None))
    clarifier = CliClarifier(console.next, err=io.StringIO())

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(clarifier.ask(request()), 0.05)
    feed.put("siguiente mensaje\n")

    assert await console.next() == "siguiente mensaje"
    feed.put(None)
