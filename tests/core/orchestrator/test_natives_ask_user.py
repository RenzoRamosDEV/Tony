import pytest

from tony.core.mcp.native import NativeScope
from tony.core.orchestrator.natives import NATIVE_TOOLS, ask_user
from tony.core.orchestrator.ports import ToolReply


class Asker:
    def __init__(self, answer="la personal"):
        self.answer = answer
        self.calls = []

    async def __call__(self, question, options):
        self.calls.append((question, options))
        return self.answer


def tool(asker=None, *, with_scope=True):
    scope = NativeScope(root=None, agent="viernes", ask_user=asker if with_scope else None)
    return ask_user(scope)


def test_registry_contains_ask_user():
    assert NATIVE_TOOLS["ask_user"] is ask_user


def test_schema_requires_question_and_allows_options():
    schema = tool(Asker()).input_schema

    assert schema["required"] == ["question"]
    assert schema["properties"]["question"]["type"] == "string"
    assert schema["properties"]["options"]["items"] == {"type": "string"}


async def test_valid_call_returns_the_answer_as_text():
    asker = Asker("Trabajo")

    reply = await tool(asker).run({"question": "¿Qué cuenta?", "options": ["Personal", "Trabajo"]})

    assert reply == ToolReply(text="Trabajo")
    assert asker.calls == [("¿Qué cuenta?", ["Personal", "Trabajo"])]


@pytest.mark.parametrize("options", [None, "absent"])
async def test_options_may_be_absent_or_null(options):
    asker = Asker()
    args = {"question": "¿Cuál?"}
    if options is None:
        args["options"] = None

    await tool(asker).run(args)

    assert asker.calls == [("¿Cuál?", [])]


async def test_empty_options_list_is_accepted():
    asker = Asker()

    await tool(asker).run({"question": "¿Cuál?", "options": []})

    assert asker.calls == [("¿Cuál?", [])]


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": 5},
        {"question": None},
        {"question": "q", "options": "a"},
        {"question": "q", "options": {"a": 1}},
        {"question": "q", "options": ["a", 2]},
    ],
)
async def test_bad_input_is_an_error_and_never_asks(args):
    asker = Asker()

    reply = await tool(asker).run(args)

    assert reply.is_error is True
    assert asker.calls == []


async def test_no_answer_is_the_documented_error():
    reply = await tool(Asker(None)).run({"question": "¿Cuál?"})

    assert reply == ToolReply(text="no answer from the user", is_error=True)


async def test_scope_without_ask_user_is_an_error():
    reply = await tool(with_scope=False).run({"question": "¿Cuál?"})

    assert reply == ToolReply(text="clarification is not available here", is_error=True)
