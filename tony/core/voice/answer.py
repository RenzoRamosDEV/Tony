import re
import unicodedata

YES = "si edith"
_RULE = re.compile(r" Regla: .*?\. ¿Autoriza\?$")


def is_voice_yes(transcript: str) -> bool:
    """Exactly «sí, Edith» once accents, case, punctuation and extra spaces are ignored."""
    decomposed = unicodedata.normalize("NFD", transcript)
    kept = (
        " " if unicodedata.category(char).startswith("P") else char
        for char in decomposed
        if not unicodedata.combining(char)
    )
    return " ".join("".join(kept).casefold().split()) == YES


def spoken_question(question: str) -> str:
    """The confirmation question without its `Regla: <rule id>.` part."""
    return _RULE.sub(" ¿Autoriza?", question)
