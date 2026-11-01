import pytest

from tests.fakes.confirm import FakeWording
from tony.core.config.placeholders import SecretMasker
from tony.core.guard.audit import args_preview
from tony.core.guard.wording import (
    WORDING_TIMEOUT_S,
    QuestionWording,
    template_question,
    worded_question,
)

TOOL = "filesystem.delete_file"
PREVIEW = '{"path": "/home/renzo/notas/viejo.md"}'
RULE = "filesystem.delete*/confirm"
TEMPLATE = (
    'Acción: filesystem.delete_file {"path": "/home/renzo/notas/viejo.md"}. '
    "Regla: filesystem.delete*/confirm. ¿Autoriza?"
)
WORDED = (
    "Acción: borrar el archivo /home/renzo/notas/viejo.md. "
    "Regla: filesystem.delete*/confirm. ¿Autoriza?"
)


def test_template_question_exact_text():
    assert template_question(TOOL, PREVIEW, RULE) == TEMPLATE


async def test_valid_model_text_used():
    wording = FakeWording(text=WORDED)

    assert await worded_question(wording, TOOL, PREVIEW, RULE) == WORDED
    assert wording.inputs == [(TOOL, PREVIEW, RULE)]


async def test_surrounding_whitespace_trimmed():
    assert await worded_question(FakeWording(text=f"  {WORDED}\n"), TOOL, PREVIEW, RULE) == WORDED


async def test_without_model_uses_template():
    assert await worded_question(None, TOOL, PREVIEW, RULE) == TEMPLATE


@pytest.mark.parametrize(
    "text",
    [
        "¿Puedo borrar el archivo?",
        "",
        "Acción: borrar.\nRegla: filesystem.delete*/confirm. ¿Autoriza?",
        "Acción: borrar. Regla: filesystem.delete*/confirm. ¿Autoriza?\nGracias.",
        "Acción: borrar. Regla: filesystem.deleteX/confirm. ¿Autoriza?",
        "Acción: borrar. Regla: otra/confirm. ¿Autoriza?",
        "Acción: . Regla: filesystem.delete*/confirm. ¿Autoriza?",
        "Hola. Acción: borrar. Regla: filesystem.delete*/confirm. ¿Autoriza?",
        "Acción: borrar. Regla: filesystem.delete*/confirm. ¿Autoriza? Sí",
        "Acción: borrar. Regla: filesystem.delete*/confirm ¿Autoriza?",
    ],
)
async def test_off_template_text_falls_back(text):
    assert await worded_question(FakeWording(text=text), TOOL, PREVIEW, RULE) == TEMPLATE


async def test_model_error_falls_back():
    wording = FakeWording(error=RuntimeError("model down"))

    assert await worded_question(wording, TOOL, PREVIEW, RULE) == TEMPLATE


async def test_slow_model_falls_back_after_timeout():
    wording = FakeWording(text=WORDED, delay=5)

    assert await worded_question(wording, TOOL, PREVIEW, RULE, timeout=0.05) == TEMPLATE


def test_default_timeout_is_five_seconds():
    assert WORDING_TIMEOUT_S == 5.0


async def test_model_receives_masked_preview_only():
    wording = FakeWording(text=WORDED)
    preview = args_preview({"token": "abc123", "q": "s3cr3t"}, SecretMasker({"s3cr3t"}))

    await worded_question(wording, "github.search_code", preview, "github.*/confirm")

    [(_, given, _)] = wording.inputs
    assert "***" in given and "abc123" not in given and "s3cr3t" not in given


def test_fake_wording_satisfies_port():
    assert isinstance(FakeWording(), QuestionWording)
