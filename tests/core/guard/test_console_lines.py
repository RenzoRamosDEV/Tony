import asyncio
import io
import queue

import pytest

from tony.core.guard.confirm import CliConfirmer, ConfirmationRequest, ConsoleLines

REQUEST = ConfirmationRequest(
    task_id="t1", tool="filesystem.delete_file", args_preview="{}", question="Acción: x. ¿Autoriza?"
)


def fed_lines():
    feed: queue.Queue[str | None] = queue.Queue()
    return feed, ConsoleLines(iter(feed.get, None))


async def answer_line(line):
    async def read_line():
        return line

    return await CliConfirmer(read_line=read_line, err=io.StringIO()).ask(REQUEST)


async def test_prefix_written_before_the_question_on_stderr():
    err = io.StringIO()

    async def read_line():
        return "s"

    await CliConfirmer(read_line=read_line, prefix="Edith: ", err=err).ask(REQUEST)

    assert err.getvalue() == "Edith: Acción: x. ¿Autoriza? "


@pytest.mark.parametrize(("line", "answer"), [(" Sí ", True), ("vale", False), (None, False)])
async def test_answers_unchanged_with_an_async_reader(line, answer):
    assert await answer_line(line) is answer


async def test_lines_arrive_in_order_and_end_of_input_is_none():
    lines = ConsoleLines(iter(["Hola\n", "adiós\n"]))

    assert [await lines.next(), await lines.next()] == ["Hola", "adiós"]
    assert await lines.next() is None
    assert await lines.next() is None


async def test_timed_out_confirmation_does_not_consume_the_next_line():
    feed, lines = fed_lines()
    confirmer = CliConfirmer(read_line=lines.next, prefix="Edith: ", err=io.StringIO())

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(confirmer.ask(REQUEST), 0.05)
    feed.put("Hola\n")

    assert await asyncio.wait_for(lines.next(), 2) == "Hola"


async def test_confirmation_reads_a_shared_line():
    feed, lines = fed_lines()
    confirmer = CliConfirmer(read_line=lines.next, err=io.StringIO())
    feed.put("s\n")

    assert await confirmer.ask(REQUEST) is True
