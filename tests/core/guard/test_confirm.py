import asyncio
import io
import subprocess
import sys
import textwrap

import pytest

from tests.fakes.confirm import FakeConfirmer
from tony.core.guard.confirm import CliConfirmer, Confirmer, NoChannelConfirmer

QUESTION = "Acción: x. Regla: r. ¿Autoriza?"


async def ask_with(line):
    err = io.StringIO()
    answer = await CliConfirmer(readline=lambda: line, err=err).ask(QUESTION)
    return answer, err.getvalue()


@pytest.mark.parametrize("line", [" Sí \n", "YES\n", "s\n", "si\n", "y\n", "yes", "SÍ\n", "Si\n"])
async def test_yes_answers(line):
    assert (await ask_with(line))[0] is True


@pytest.mark.parametrize("line", ["vale\n", "\n", "", None, "no\n", "sii\n", "s í\n", "ys\n"])
async def test_other_answers_and_end_of_input_mean_no(line):
    assert (await ask_with(line))[0] is False


async def test_question_written_to_stderr_only(capsys):
    _, err = await ask_with("s\n")

    assert err == f"{QUESTION} "
    assert capsys.readouterr().out == ""


async def test_never_answering_readline_is_bounded_by_outer_timeout():
    blocked = CliConfirmer(readline=lambda: __import__("time").sleep(60), err=io.StringIO())

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(blocked.ask(QUESTION), 0.05)


def test_blocked_reader_does_not_keep_interpreter_alive():
    script = textwrap.dedent(
        """
        import asyncio, io, threading
        from tony.core.guard.confirm import CliConfirmer

        async def main():
            confirmer = CliConfirmer(readline=threading.Event().wait, err=io.StringIO())
            try:
                await asyncio.wait_for(confirmer.ask("q"), 0.05)
            except TimeoutError:
                print("timed out")

        asyncio.run(main())
        """
    )

    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=10
    )

    assert (done.returncode, done.stdout) == (0, "timed out\n")


async def test_no_channel_answers_no():
    assert await NoChannelConfirmer().ask(QUESTION) is False


@pytest.mark.parametrize(
    "confirmer", [NoChannelConfirmer(), CliConfirmer(readline=lambda: ""), FakeConfirmer()]
)
def test_confirmers_satisfy_port(confirmer):
    assert isinstance(confirmer, Confirmer)
