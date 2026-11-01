import io

from tony.apps.cli.chat import PIN_PROMPT, ChatPrinter, TerminalPinPrompt
from tony.core.events import core_events as ev
from tony.core.guard.session import AuthStatus


def printer():
    out, err = io.StringIO(), io.StringIO()
    return ChatPrinter(out, err), out, err


def test_tokens_then_turn_result_form_one_line():
    publish, out, _ = printer()

    publish(ev.token("jarvis", "Buenas"))
    publish(ev.token("jarvis", " tardes"))
    publish(ev.turn_result("jarvis", "Buenas tardes", "auto"))

    assert out.getvalue() == "Jarvis: Buenas tardes\n"


def test_turn_result_without_tokens_prints_the_text():
    publish, out, _ = printer()

    publish(ev.turn_result("viernes", "Hecho.", "auto"))

    assert out.getvalue() == "Viernes: Hecho.\n"


def test_progress_closes_an_open_line_and_prints_its_own():
    publish, out, _ = printer()

    publish(ev.token("jarvis", "Voy"))
    publish(ev.progress("jarvis", "Un momento, señor; estoy en ello."))

    assert out.getvalue() == "Jarvis: Voy\nJarvis: Un momento, señor; estoy en ello.\n"


def test_error_goes_to_stderr_after_closing_the_line():
    publish, out, err = printer()

    publish(ev.token("jarvis", "Voy"))
    publish(ev.error("front", "model down"))

    assert (out.getvalue(), err.getvalue()) == ("Jarvis: Voy\n", "tony: model down\n")


def test_other_events_print_nothing():
    publish, out, err = printer()

    publish(ev.task_started("t", "viernes", "x"))
    publish(ev.mcp_status("viernes", "fs", up=True, reason=None))
    publish(ev.reply_mode("text"))

    assert out.getvalue() == err.getvalue() == ""


def pin_prompt(answer):
    asked, err = [], io.StringIO()

    def getpass(prompt):
        asked.append(prompt)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return TerminalPinPrompt(getpass, err), asked, err


async def test_pin_prompt_returns_the_entry():
    prompt, asked, err = pin_prompt("4821")

    assert await prompt.request(AuthStatus("locked", "start", 0)) == "4821"
    assert asked == [PIN_PROMPT]
    assert err.getvalue() == ""


async def test_empty_entry_or_end_of_input_cancels():
    for answer in ("", EOFError()):
        prompt, *_ = pin_prompt(answer)
        assert await prompt.request(AuthStatus("locked", "start", 0)) is None


async def test_wrong_pin_and_wait_are_announced():
    prompt, _, err = pin_prompt("1")

    await prompt.request(AuthStatus("locked", "wrong_pin", 0))
    await prompt.request(AuthStatus("locked", "backoff", 0))

    assert err.getvalue() == "Edith: PIN incorrecto.\n"


async def test_back_off_waits_before_asking(monkeypatch):
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("tony.apps.cli.chat.asyncio.sleep", sleep)
    prompt, _, err = pin_prompt("1")

    await prompt.request(AuthStatus("locked", "wrong_pin", 10))

    assert slept == [10]
    assert err.getvalue() == "Edith: PIN incorrecto.\nEdith: espere 10 s.\n"
