import gc
import weakref

import pytest

from tests.core.orchestrator.test_claude_engine import (
    STRUCTURED,
    FakeSdkClient,
    assistant,
    result_message,
)
from tony.core.events.messages import TaskRequest
from tony.core.loader.agent_md import AgentSpec
from tony.core.orchestrator.claude_engine import ClaudeEngine, EngineError, OutcomeAccumulator
from tony.core.orchestrator.ports import EngineOutcome, Usage

SPEC = AgentSpec(
    name="jarvis",
    role="front",
    model="claude-haiku",
    persona={"language": "es", "tone": "t"},
    voice={"tts": "kokoro/em_alex"},
    system_prompt="Cuerpo",
)


def test_empty_accumulator_yields_empty_outcome():
    assert OutcomeAccumulator().outcome() == EngineOutcome(text="")


def test_latest_non_empty_assistant_text_wins_without_a_result():
    accumulator = OutcomeAccumulator()
    accumulator.add(assistant("uno"))
    accumulator.add(assistant("dos"))
    accumulator.add(assistant(""))

    assert accumulator.outcome() == EngineOutcome(text="dos")


def test_result_gives_text_structured_output_and_usage():
    accumulator = OutcomeAccumulator()
    accumulator.add(assistant("pensando"))
    accumulator.add(result_message())

    assert accumulator.outcome() == EngineOutcome(
        text="texto final", structured=STRUCTURED, usage=[Usage(120, 30, 5)]
    )


def test_result_without_text_falls_back_to_last_assistant_text():
    accumulator = OutcomeAccumulator()
    accumulator.add(assistant("respaldo"))
    accumulator.add(result_message(result=None))

    assert accumulator.outcome().text == "respaldo"


def test_missing_usage_counts_as_zero():
    accumulator = OutcomeAccumulator()
    accumulator.add(result_message(usage=None))

    assert accumulator.outcome().usage == [Usage(0, 0)]


@pytest.mark.parametrize(
    ("result", "expected"),
    [("boom", "error_during_execution: boom"), (None, "error_during_execution")],
)
def test_error_result_raises(result, expected):
    accumulator = OutcomeAccumulator()
    accumulator.add(result_message(is_error=True, subtype="error_during_execution", result=result))

    with pytest.raises(EngineError) as raised:
        accumulator.outcome()

    assert str(raised.value) == expected


class StreamingClient(FakeSdkClient):
    """Yields messages built on the fly, so only a consumer that keeps them can keep them alive."""

    def __init__(self, options, probes):
        super().__init__(options, [])
        self.probes = probes

    async def receive_response(self):
        for text in ("uno", "dos"):
            message = assistant(text)
            self.probes.append(weakref.ref(message))
            yield message
        yield result_message()


async def test_run_does_not_retain_streamed_messages():
    probes = []
    engine = ClaudeEngine(lambda options: StreamingClient(options, probes))

    outcome = await engine.run(SPEC, TaskRequest(objetivo="t"), [], "m")

    gc.collect()
    assert outcome.text == "texto final"
    assert [probe() for probe in probes] == [None, None]


async def test_converse_does_not_retain_streamed_messages():
    probes = []
    engine = ClaudeEngine(lambda options: StreamingClient(options, probes))

    outcome = await engine.converse(SPEC, "sys", "hola", [], "m", lambda chunk: None)

    gc.collect()
    assert outcome.text == "texto final"
    assert [probe() for probe in probes] == [None, None]


def test_usage_defaults_keep_two_argument_construction_working():
    usage = Usage(1, 2)

    assert (usage.cache_read_tokens, usage.cache_creation_tokens, usage.cost_usd) == (0, 0, None)


def test_result_fills_cache_tokens_and_cost():
    accumulator = OutcomeAccumulator()
    accumulator.add(
        result_message(
            usage={
                "input_tokens": 7,
                "output_tokens": 3,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 100,
            },
            total_cost_usd=0.012,
        )
    )

    assert accumulator.outcome().usage == [Usage(7, 3, 900, 100, 0.012)]


def test_result_without_cost_or_cache_keys_reports_zero_cache_and_unknown_cost():
    accumulator = OutcomeAccumulator()
    accumulator.add(result_message(usage={"input_tokens": 7, "output_tokens": 3}))

    [usage] = accumulator.outcome().usage
    assert (usage.cache_read_tokens, usage.cache_creation_tokens) == (0, 0)
    assert usage.cost_usd is None


def test_zero_cost_is_kept_as_zero():
    accumulator = OutcomeAccumulator()
    accumulator.add(result_message(total_cost_usd=0.0))

    assert accumulator.outcome().usage[0].cost_usd == 0.0
