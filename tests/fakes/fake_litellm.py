"""Scripted, offline replacement for litellm.acompletion."""

from copy import deepcopy
from types import SimpleNamespace


def response(content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 2, "completion_tokens": 3}),
    )


def tool_call(name="fs_read", arguments='{"path":"a"}', call_id="call-1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class FakeCompletion:
    def __init__(self, *script):
        self.script = iter(script)
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        item = next(self.script)
        if isinstance(item, Exception):
            raise item
        return item
