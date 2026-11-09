import asyncio
import re
from typing import Protocol, runtime_checkable

WORDING_TIMEOUT_S = 5.0


@runtime_checkable
class QuestionWording(Protocol):
    async def word(self, tool: str, preview: str, rule: str) -> str: ...


def template_question(tool: str, preview: str, rule: str) -> str:
    return f"Acción: {tool} {preview}. Regla: {rule}. ¿Autoriza?"


def is_valid_question(text: str, rule: str) -> bool:
    return re.fullmatch(rf"Acción: .+\. Regla: {re.escape(rule)}\. ¿Autoriza\?", text) is not None


async def worded_question(
    wording: QuestionWording | None,
    tool: str,
    preview: str,
    rule: str,
    *,
    timeout: float = WORDING_TIMEOUT_S,
) -> str:
    if wording is not None:
        try:
            text = (await asyncio.wait_for(wording.word(tool, preview, rule), timeout)).strip()
        except Exception:
            text = ""
        if is_valid_question(text, rule):
            return text
    return template_question(tool, preview, rule)
