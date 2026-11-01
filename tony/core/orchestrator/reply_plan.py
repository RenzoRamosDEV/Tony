from typing import NamedTuple

from tony.core.events.core_events import Origin, ReplyMode


class ReplyPlan(NamedTuple):
    speaks: bool
    writes: bool


_WRITE_ONLY = ReplyPlan(speaks=False, writes=True)
_PLANS: dict[ReplyMode, ReplyPlan] = {
    "voice": ReplyPlan(speaks=True, writes=False),
    "text": _WRITE_ONLY,
    "both": ReplyPlan(speaks=True, writes=True),
}


def reply_plan(mode: ReplyMode, origin: Origin, voice_ready: bool) -> ReplyPlan:
    if not voice_ready:
        return _WRITE_ONLY
    if mode == "auto":
        mode = "voice" if origin == "voice" else "text"
    return _PLANS[mode]
