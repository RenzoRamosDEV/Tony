"""The conversation judge: fixed prompt, structured verdict, tolerant parsing (specs/evals)."""

from __future__ import annotations

from typing import Any

from tony.core.evals.judge import INVALID_VERDICT, JUDGE_PROMPT, JUDGE_SCHEMA, Verdict, judge


class FakeOneShot:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, prompt: str, schema: dict[str, Any]) -> Any:
        self.calls.append((prompt, schema))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_prompt_contains_criterion_and_reply_and_asks_for_the_schema() -> None:
    one_shot = FakeOneShot({"pass": True, "reason": "correcta"})

    verdict = await judge(one_shot, "Responde la hora sin inventar", "Son las 10:05.")

    prompt, schema = one_shot.calls[0]
    assert "Responde la hora sin inventar" in prompt and "Son las 10:05." in prompt
    assert prompt.startswith(JUDGE_PROMPT.split("{", 1)[0])
    assert schema == JUDGE_SCHEMA
    assert verdict == Verdict(passed=True, reason="correcta")


async def test_negative_verdict_keeps_the_reason() -> None:
    verdict = await judge(FakeOneShot({"pass": False, "reason": "inventa la hora"}), "c", "r")

    assert verdict.passed is False and verdict.reason == "inventa la hora"


async def test_json_text_answer_is_parsed() -> None:
    verdict = await judge(FakeOneShot('{"pass": false, "reason": "x"}'), "c", "r")

    assert verdict == Verdict(passed=False, reason="x")


async def test_invalid_or_failing_answers_fail_with_a_fixed_reason() -> None:
    assert (await judge(FakeOneShot("no json"), "c", "r")) == Verdict(False, INVALID_VERDICT)
    assert (await judge(FakeOneShot({"pass": "maybe"}), "c", "r")) == Verdict(
        False, INVALID_VERDICT
    )
    assert (await judge(FakeOneShot(RuntimeError("red")), "c", "r")).passed is False


async def test_failing_judge_call_reports_the_exception() -> None:
    verdict = await judge(FakeOneShot(RuntimeError("red")), "c", "r")

    assert verdict == Verdict(False, f"{INVALID_VERDICT}: red")


async def test_missing_reason_defaults_to_empty() -> None:
    assert (await judge(FakeOneShot({"pass": True}), "c", "r")) == Verdict(True, "")
