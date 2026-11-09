from collections import OrderedDict
from collections.abc import Callable

from tony.core.guard.wording import QuestionWording, is_valid_question

CACHE_SIZE = 128

_Key = tuple[str, str, str, str, str]


class WordingCache:
    """In-memory LRU of accepted confirmation questions."""

    def __init__(self, size: int = CACHE_SIZE) -> None:
        self._size = size
        self._entries: OrderedDict[_Key, str] = OrderedDict()

    def get(self, key: _Key) -> str | None:
        question = self._entries.get(key)
        if question is not None:
            self._entries.move_to_end(key)
        return question

    def put(self, key: _Key, question: str) -> None:
        self._entries[key] = question
        self._entries.move_to_end(key)
        if len(self._entries) > self._size:
            self._entries.popitem(last=False)


class CachingWording:
    """QuestionWording decorator reusing questions that passed the format check."""

    def __init__(
        self, inner: QuestionWording, cache: WordingCache, system_prompt: str, model_id: str
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._system_prompt = system_prompt
        self._model_id = model_id

    async def word(self, tool: str, preview: str, rule: str) -> str:
        key = (self._system_prompt, self._model_id, tool, preview, rule)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        text = await self._inner.word(tool, preview, rule)
        question = text.strip()
        if is_valid_question(question, rule):
            self._cache.put(key, question)
        return text


def cached_wording_factory(
    build: Callable[[str, str], QuestionWording],
) -> Callable[[str, str], QuestionWording]:
    """Wrap a wording factory so every wording it builds shares one process-wide cache."""
    cache = WordingCache()

    def build_cached(system_prompt: str, model_id: str) -> QuestionWording:
        return CachingWording(build(system_prompt, model_id), cache, system_prompt, model_id)

    return build_cached
