"""Portable ReAct engine using LiteLLM and Tony's shared execution barrier.

Voice streaming deliberately degrades to one on_text/on_speech callback at the end
of each turn: providers return a complete structured FrontReply, not voice chunks.
Unstructured worker text is accepted as a partial result (the degraded fallback).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.runner.cancel import USER_REASON, CancelToken
from tony.core.runner.contracts import TaskRequest, TaskResult
from tony.core.runner.conversation import FrontTurn
from tony.core.runner.front_prompt import build_front_system_prompt
from tony.core.runner.portable_native import PortableNativeTools
from tony.core.runner.ports import EventSink
from tony.core.runner.proxy import TaskState, ToolBarrier, ToolCaller, text_reply
from tony.core.runner.reply_mode import FrontReply
from tony.core.runner.results import cancelled_result, error_result
from tony.core.runner.strict_schema import strict_schema

Completion = Callable[..., Awaitable[Any]]
TextCallback = Callable[[str], Awaitable[None]]


def _tool_definitions(catalog: ToolCatalog) -> tuple[list[dict[str, Any]], dict[str, str]]:
    definitions, names = [], {}
    for refs in catalog.servers().values():
        for ref in refs:
            base = re.sub(r"[^a-zA-Z0-9_-]", "_", ref.qualified)[:64] or "tool"
            name = base
            index = 1
            while name in names:
                suffix = f"_{index}"
                name = base[: 64 - len(suffix)] + suffix
                index += 1
            names[name] = ref.qualified
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": ref.description,
                        "parameters": ref.input_schema,
                    },
                }
            )
    return definitions, names


def _parse(content: str, schema: type[BaseModel]) -> BaseModel | None:
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        # Providers without schema support may wrap the JSON in prose or fences.
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", content):
            try:
                value, _ = decoder.raw_decode(content[match.start() :])
                return schema.model_validate(value)
            except (ValueError, ValidationError):
                continue
        return None
    try:
        return schema.model_validate(value)
    except ValidationError as exc:
        raise ValueError(f"La salida no cumple el esquema de {schema.__name__}.") from exc


async def _until_cancelled(awaitable: Awaitable[Any], state: TaskState) -> Any:
    response = asyncio.ensure_future(awaitable)
    cancelled = asyncio.create_task(state.cancel_token.wait())
    try:
        await asyncio.wait({response, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        if state.cancelled:
            raise ValueError(cancelled_result(state).errores[0])
        return await response
    finally:
        for task in (response, cancelled):
            if not task.done():
                task.cancel()
        await asyncio.gather(response, cancelled, return_exceptions=True)


class _Loop:
    def __init__(
        self,
        settings: TonySettings,
        gate: ConfirmGate,
        call: ToolCaller,
        completion: Completion | None,
    ) -> None:
        self.settings, self.gate, self.call = settings, gate, call
        self.completion = completion

    def diagnostic(self, spec: AgentSpec, exc: Exception) -> str:
        if self.settings.engines[spec.engine].auth == "api_key":
            return "No pude completar la solicitud con la API. Revisa clave, modelo y cuota."
        return f"No pude completar la solicitud con LiteLLM: {exc}"

    async def run(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        events: EventSink,
        state: TaskState,
        messages: list[dict[str, Any]],
        schema: type[BaseModel],
        usage: dict[str, Any],
        native_handlers: Any = None,
    ) -> str:
        # Lazy import avoids loading provider integrations for other engines.
        import litellm

        profile = self.settings.engines[spec.engine]
        model = profile.model
        explicit_key = profile.api_key.get_secret_value() if profile.api_key else None
        if profile.auth == "api_key" and not explicit_key:
            raise ValueError("Configura la API key del motor seleccionado.")
        missing = litellm.validate_environment(model=model).get("missing_keys", [])
        if missing and not explicit_key:
            raise ValueError(f"Faltan variables de entorno para LiteLLM: {', '.join(missing)}")
        completion = self.completion or litellm.acompletion
        native = PortableNativeTools(spec.tools.native, native_handlers, events)
        definitions, names = _tool_definitions(catalog.merge(native.catalog))
        limits = self.settings.limits
        barrier = ToolBarrier(
            catalog,
            self.call,
            self.gate,
            events,
            state,
            limits.tool_timeout_s,
            limits.confirm_timeout_s,
        )
        options: dict[str, Any] = {
            "model": model,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": strict_schema(schema),
                    "strict": True,
                },
            },
        }
        if explicit_key:
            options["api_key"] = explicit_key
            options["api_base"] = (
                "https://api.openai.com/v1"
                if model.startswith("openai/")
                else "https://api.anthropic.com"
            )
        if definitions:
            options.update(tools=definitions, tool_choice="auto")
        for _ in range(spec.max_steps):
            if state.cancelled:
                raise ValueError(cancelled_result(state).errores[0])
            try:
                response = await _until_cancelled(completion(messages=messages, **options), state)
            except litellm.UnsupportedParamsError as exc:
                if "response_format" not in options or "response_format" not in str(exc):
                    raise
                del options["response_format"]
                response = await _until_cancelled(completion(messages=messages, **options), state)
            response_usage = getattr(response, "usage", None)
            if response_usage is not None:
                data = response_usage.model_dump()
                for source, target in (
                    ("prompt_tokens", "input_tokens"),
                    ("completion_tokens", "output_tokens"),
                ):
                    usage[target] = usage.get(target, 0) + (data.get(source) or 0)
            message = response.choices[0].message
            calls = message.tool_calls or []
            assistant: dict[str, Any] = {"role": "assistant", "content": message.content}
            if calls:
                assistant["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in calls
                ]
            messages.append(assistant)
            if not calls:
                if not isinstance(message.content, str) or not message.content.strip():
                    raise ValueError("LiteLLM no devolvió una respuesta final.")
                return message.content
            for call in calls:
                try:
                    qualified = names[call.function.name]
                    args = json.loads(call.function.arguments)
                    if not isinstance(args, dict):
                        raise ValueError("los argumentos deben ser un objeto JSON")
                except (KeyError, ValueError, TypeError):
                    reply = text_reply(
                        "Tool desconocida o argumentos JSON inválidos.", is_error=True
                    )
                else:
                    if qualified in native.catalog:
                        reply = await native.call(qualified, args)
                    else:
                        reply = await barrier.handler(qualified)(args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": "\n".join(
                            block["text"] for block in reply["content"] if block["type"] == "text"
                        ),
                    }
                )
            if state.cancelled:
                raise ValueError(cancelled_result(state).errores[0])
        raise ValueError(f"Se alcanzó el límite de {spec.max_steps} pasos sin respuesta final.")


class LiteLlmRunner:
    def __init__(
        self,
        settings: TonySettings,
        task_id: str,
        gate: ConfirmGate,
        call: ToolCaller,
        completion: Completion | None = None,
        cancel_token: CancelToken | None = None,
        native_handlers: Any = None,
    ) -> None:
        self._settings, self._task_id = settings, task_id
        self._cancel_token = cancel_token
        self._native_handlers = native_handlers
        self._loop = _Loop(settings, gate, call, completion)

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult:
        events.emit("task.started", {"agent": spec.name, **request.model_dump()})
        state = TaskState(self._task_id, cancel_token=self._cancel_token or CancelToken())
        messages = [
            {"role": "system", "content": spec.system_prompt},
            {"role": "user", "content": request.model_dump_json()},
        ]
        usage: dict[str, Any] = {}
        try:
            content = await self._loop.run(
                spec, tools, events, state, messages, TaskResult, usage, self._native_handlers
            )
            parsed = _parse(content, TaskResult)
            result = (
                parsed
                if isinstance(parsed, TaskResult)
                else TaskResult(status="partial", resumen=content, pasos=list(state.steps))
            )
        except Exception as exc:  # noqa: BLE001 - engine errors cross the port as TaskResult
            result = error_result(
                self._loop.diagnostic(spec, exc),
                state.steps,
            )
        if state.cancelled:
            result = cancelled_result(state)
        events.emit("task.finished", {"status": result.status, "usage": usage})
        return result


class LiteLlmConversation:
    """Local history is the session; callbacks run once after the complete reply."""

    def __init__(
        self,
        settings: TonySettings,
        gate: ConfirmGate,
        call: ToolCaller,
        completion: Completion | None = None,
    ) -> None:
        self._loop = _Loop(settings, gate, call, completion)
        self._messages: list[dict[str, Any]] = []
        self._events: EventSink | None = None
        self._state: TaskState | None = None
        self.session_id: str | None = None

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: Any,
        events: EventSink,
        resume: str | None = None,
    ) -> None:
        # There is no remote session to resume. Only this object's history is recoverable.
        if resume is not None and resume != self.session_id:
            raise ValueError("LiteLLM no puede recuperar una sesión sin su historial local.")
        self._spec, self._catalog, self._events = spec, catalog, events
        self._native_handlers = handlers
        if resume is None:
            self.session_id = str(uuid4())
            self._messages = [
                {"role": "system", "content": build_front_system_prompt(spec, spec.tools.native)}
            ]

    async def turn(
        self,
        prompt: str,
        on_text: TextCallback | None = None,
        on_speech: TextCallback | None = None,
    ) -> FrontTurn:
        if self._events is None:
            raise RuntimeError("La conversación no está abierta.")
        if self._state is not None:
            raise RuntimeError("Ya hay un turno en curso.")
        events = self._events
        state = self._state = TaskState("front")
        messages = [*self._messages, {"role": "user", "content": prompt}]
        usage: dict[str, Any] = {}
        try:
            content = await self._loop.run(
                self._spec,
                self._catalog,
                events,
                state,
                messages,
                FrontReply,
                usage,
                self._native_handlers,
            )
            parsed = _parse(content, FrontReply)
        except Exception as exc:  # noqa: BLE001 - provider errors become failed turns
            diagnostic = self._loop.diagnostic(self._spec, exc)
            events.emit("turn.error", {"diagnostic": diagnostic})
            return FrontTurn(text=diagnostic, error=diagnostic, usage=usage)
        finally:
            self._state = None
        self._messages = messages
        reply = parsed if isinstance(parsed, FrontReply) else FrontReply(display_text=content)
        if on_text is not None:
            await on_text(reply.display_text)
        if on_speech is not None:
            await on_speech(reply.speech_text or reply.display_text)
        return FrontTurn(
            text=reply.display_text,
            structured=parsed.model_dump() if parsed is not None else None,
            usage=usage,
        )

    async def interrupt(self) -> None:
        if self._state is not None:
            self._state.cancel_token.cancel(USER_REASON)

    async def close(self) -> None:
        await self.interrupt()
        self._messages = []
        self._events = None
        self.session_id = None


def litellm_runner_factory(
    settings: TonySettings,
    task_id: str,
    gate: ConfirmGate,
    call: ToolCaller,
    token: CancelToken,
    native_handlers: Any = None,
) -> LiteLlmRunner:
    return LiteLlmRunner(
        settings, task_id, gate, call, cancel_token=token, native_handlers=native_handlers
    )
