import pytest

from tony.core.voice.answer import is_voice_yes, spoken_question


@pytest.mark.parametrize(
    "transcript",
    [
        "Sí, Edith.",
        "¡SÍ, Edith!",
        " si   edith ",
        "Si Edith",
        "sí edith",
        "Sí… Edith?",
        "SI\tEDITH",
    ],
)
def test_yes(transcript):
    assert is_voice_yes(transcript) is True


@pytest.mark.parametrize(
    "transcript",
    ["vale", "sí", "sí edith por favor", "no, Edith", "", "   ", "siedith", "sí, edit", "edith sí"],
)
def test_anything_else_is_no(transcript):
    assert is_voice_yes(transcript) is False


QUESTION = (
    "Acción: borrar el archivo /home/renzo/notas/viejo.md. "
    "Regla: filesystem.delete*/confirm. ¿Autoriza?"
)


def test_spoken_question_drops_the_rule():
    assert spoken_question(QUESTION) == (
        "Acción: borrar el archivo /home/renzo/notas/viejo.md. ¿Autoriza?"
    )


@pytest.mark.parametrize(
    "question",
    [
        "Acción: borrar el archivo viejo.md. ¿Autoriza?",
        "Regla: x. ¿Autoriza?",
        "Acción: x. Regla: y. ¿Lo autoriza?",
    ],
)
def test_question_without_a_trailing_rule_is_unchanged(question):
    assert spoken_question(question) == question
