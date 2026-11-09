import pytest

from tests.fakes.confirm import FakeWording
from tony.core.guard.caching_wording import (
    CACHE_SIZE,
    CachingWording,
    WordingCache,
    cached_wording_factory,
)
from tony.core.guard.wording import QuestionWording, is_valid_question

TOOL = "filesystem.delete_file"
PREVIEW = '{"path": "/a.md"}'
RULE = "filesystem.delete*/confirm"
VALID = f"Acción: borrar /a.md. Regla: {RULE}. ¿Autoriza?"


def caching(inner, cache=None, prompt="p", model="m"):
    return CachingWording(inner, cache or WordingCache(), prompt, model)


def test_cache_size_is_128():
    assert CACHE_SIZE == 128


async def test_second_identical_question_makes_no_model_call():
    inner = FakeWording(text=VALID)
    wording = caching(inner)

    first = await wording.word(TOOL, PREVIEW, RULE)
    second = await wording.word(TOOL, PREVIEW, RULE)

    assert first == second == VALID
    assert len(inner.inputs) == 1


async def test_padded_valid_wording_is_cached_trimmed():
    inner = FakeWording(text=f"  {VALID}\n")
    wording = caching(inner)

    await wording.word(TOOL, PREVIEW, RULE)

    assert await wording.word(TOOL, PREVIEW, RULE) == VALID
    assert len(inner.inputs) == 1


@pytest.mark.parametrize("text", ["¿Puedo borrar el archivo?", "", "   "])
async def test_invalid_or_empty_wording_is_not_cached(text):
    inner = FakeWording(text=text)
    wording = caching(inner)

    await wording.word(TOOL, PREVIEW, RULE)
    await wording.word(TOOL, PREVIEW, RULE)

    assert len(inner.inputs) == 2


async def test_failure_propagates_and_is_not_cached():
    inner = FakeWording(error=RuntimeError("down"))
    wording = caching(inner)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await wording.word(TOOL, PREVIEW, RULE)

    assert len(inner.inputs) == 2


async def test_different_args_rule_tool_each_miss():
    inner = FakeWording(text=VALID)
    wording = caching(inner)
    other_rule = "other/confirm"
    inner_other = FakeWording(text=f"Acción: x. Regla: {other_rule}. ¿Autoriza?")

    await wording.word(TOOL, PREVIEW, RULE)
    await wording.word(TOOL, '{"path": "/b.md"}', RULE)
    await wording.word("filesystem.move", PREVIEW, RULE)
    assert len(inner.inputs) == 3

    other = caching(inner_other)
    await other.word(TOOL, PREVIEW, other_rule)
    await other.word(TOOL, PREVIEW, other_rule)
    assert len(inner_other.inputs) == 1


async def test_prompt_and_model_are_part_of_the_key():
    cache = WordingCache()
    inner = FakeWording(text=VALID)

    await caching(inner, cache, "p1", "m").word(TOOL, PREVIEW, RULE)
    await caching(inner, cache, "p2", "m").word(TOOL, PREVIEW, RULE)
    await caching(inner, cache, "p1", "m2").word(TOOL, PREVIEW, RULE)
    await caching(inner, cache, "p1", "m").word(TOOL, PREVIEW, RULE)

    assert len(inner.inputs) == 3


async def test_least_recently_used_entry_is_evicted_at_128():
    inner = FakeWording(text=VALID)
    wording = caching(inner)
    for index in range(CACHE_SIZE):
        await wording.word(TOOL, f"arg{index}", RULE)
    await wording.word(TOOL, "arg0", RULE)  # refresh the oldest
    await wording.word(TOOL, "extra", RULE)  # evicts arg1, not arg0
    calls = len(inner.inputs)

    await wording.word(TOOL, "arg0", RULE)
    assert len(inner.inputs) == calls
    await wording.word(TOOL, "arg1", RULE)
    assert len(inner.inputs) == calls + 1


async def test_exactly_128_entries_all_stay_cached():
    inner = FakeWording(text=VALID)
    wording = caching(inner)
    for index in range(CACHE_SIZE):
        await wording.word(TOOL, f"arg{index}", RULE)

    await wording.word(TOOL, "arg0", RULE)

    assert len(inner.inputs) == CACHE_SIZE


async def test_factory_shares_the_cache_across_built_wordings():
    inners = []

    def build(prompt, model):
        inners.append(FakeWording(text=VALID))
        return inners[-1]

    factory = cached_wording_factory(build)

    await factory("p", "m").word(TOOL, PREVIEW, RULE)
    await factory("p", "m").word(TOOL, PREVIEW, RULE)

    assert sum(len(inner.inputs) for inner in inners) == 1


def test_caching_wording_satisfies_port():
    assert isinstance(caching(FakeWording()), QuestionWording)


@pytest.mark.parametrize(
    ("text", "valid"),
    [
        (VALID, True),
        ("Acción: . Regla: filesystem.delete*/confirm. ¿Autoriza?", False),
        ("", False),
    ],
)
def test_is_valid_question(text, valid):
    assert is_valid_question(text, RULE) is valid


async def test_different_rule_misses_in_a_shared_cache():
    other_rule = "other/confirm"
    inner = FakeWording(text=VALID)
    wording = caching(inner)

    await wording.word(TOOL, PREVIEW, RULE)
    await wording.word(TOOL, PREVIEW, other_rule)

    assert len(inner.inputs) == 2
