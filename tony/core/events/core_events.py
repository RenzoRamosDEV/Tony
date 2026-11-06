import dataclasses
from collections.abc import Callable
from datetime import UTC
from typing import Any, Literal

from tony.core.config.placeholders import SecretMasker
from tony.core.events.log_events import Outcome
from tony.core.events.messages import Ruling, TaskResult
from tony.core.logging.task_log import Clock, utc_now

Event = dict[str, Any]
Publisher = Callable[[Event], None]
ReplyMode = Literal["auto", "voice", "text", "both"]
Origin = Literal["text", "voice"]
VoiceLevelSource = Literal["input", "output"]
VoiceState = Literal["loading", "ready", "listening", "unavailable"]
AuthState = Literal["locked", "unlocked"]
AuthReason = Literal[
    "start", "no_lock_file", "wrong_pin", "backoff", "idle", "cancelled", "unlocked", "not_required"
]


def no_op(event: Event) -> None:
    return None


class MaskingPublisher:
    def __init__(self, masker: SecretMasker, inner: Publisher) -> None:
        self._masker = masker
        self._inner = inner

    def __call__(self, event: Event) -> None:
        self._inner(self._masker.mask_json(event))


def _event(kind: str, clock: Clock, **fields: Any) -> Event:
    return {"type": kind, "ts": clock().astimezone(UTC).isoformat(), **fields}


def token(agent: str, text: str, *, clock: Clock = utc_now) -> Event:
    return _event("token", clock, agent=agent, text=text)


def progress(agent: str, text: str, *, clock: Clock = utc_now) -> Event:
    return _event("progress", clock, agent=agent, text=text)


def task_started(task_id: str, agent: str, objetivo: str, *, clock: Clock = utc_now) -> Event:
    return _event("task_started", clock, task_id=task_id, agent=agent, objetivo=objetivo)


def tool_call(
    task_id: str,
    agent: str,
    tool: str,
    args_preview: str,
    ruling: Ruling,
    *,
    clock: Clock = utc_now,
) -> Event:
    return _event(
        "tool_call",
        clock,
        task_id=task_id,
        agent=agent,
        tool=tool,
        args_preview=args_preview,
        **ruling.model_dump(),
    )


def needs_confirmation(
    task_id: str,
    tool: str,
    args_preview: str,
    question: str,
    allow_always: bool,
    *,
    clock: Clock = utc_now,
) -> Event:
    return _event(
        "needs_confirmation",
        clock,
        task_id=task_id,
        tool=tool,
        args_preview=args_preview,
        question=question,
        allow_always=allow_always,
    )


def task_result(
    task_id: str,
    agent: str,
    outcome: Outcome,
    result: TaskResult,
    *,
    input_tokens: int,
    output_tokens: int,
    elapsed_ms: int,
    clock: Clock = utc_now,
) -> Event:
    return _event(
        "result",
        clock,
        scope="task",
        task_id=task_id,
        agent=agent,
        outcome=outcome,
        result=result.model_dump(mode="json"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_ms=elapsed_ms,
    )


def turn_result(agent: str, text: str, reply_mode: ReplyMode, *, clock: Clock = utc_now) -> Event:
    return _event("result", clock, scope="turn", agent=agent, text=text, reply_mode=reply_mode)


def token_alert(task_id: str, *, total_tokens: int, limit: int, clock: Clock = utc_now) -> Event:
    return _event("token_alert", clock, task_id=task_id, total_tokens=total_tokens, limit=limit)


def mcp_status(
    agent: str, server: str, *, up: bool, reason: str | None, clock: Clock = utc_now
) -> Event:
    return _event("mcp_status", clock, agent=agent, server=server, up=up, reason=reason)


def error(source: str, message: str, *, clock: Clock = utc_now) -> Event:
    return _event("error", clock, source=source, message=message)


def auth(state: AuthState, reason: AuthReason, retry_in_s: int, *, clock: Clock = utc_now) -> Event:
    return _event("auth", clock, state=state, reason=reason, retry_in_s=retry_in_s)


def reply_mode(mode: ReplyMode, *, clock: Clock = utc_now) -> Event:
    return _event("reply_mode", clock, mode=mode)


def turn_started(
    agent: str,
    origin: Origin,
    reply_mode: ReplyMode,
    *,
    speaks: bool,
    writes: bool,
    clock: Clock = utc_now,
) -> Event:
    return _event(
        "turn_started",
        clock,
        agent=agent,
        origin=origin,
        reply_mode=reply_mode,
        speaks=speaks,
        writes=writes,
    )


def transcript(text: str, *, clock: Clock = utc_now) -> Event:
    return _event("transcript", clock, text=text)


def voice_state(state: VoiceState, reason: str | None = None, *, clock: Clock = utc_now) -> Event:
    return _event("voice_state", clock, state=state, reason=reason)


def voice_level(source: VoiceLevelSource, level: float, *, clock: Clock = utc_now) -> Event:
    return _event("voice_level", clock, source=source, level=level)


def audio_devices(
    input: tuple[Any, ...],
    output: tuple[Any, ...],
    *,
    selected_input: str | None,
    selected_output: str | None,
    input_fallback_warning: str | None = None,
    output_fallback_warning: str | None = None,
    clock: Clock = utc_now,
) -> Event:
    return _event(
        "audio_devices",
        clock,
        input=[dataclasses.asdict(device) for device in input],
        output=[dataclasses.asdict(device) for device in output],
        selected_input=selected_input,
        selected_output=selected_output,
        input_fallback_warning=input_fallback_warning,
        output_fallback_warning=output_fallback_warning,
    )
