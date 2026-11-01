import pytest

from tony.core.orchestrator.reply_plan import ReplyPlan, reply_plan

SPEAK = ReplyPlan(speaks=True, writes=False)
WRITE = ReplyPlan(speaks=False, writes=True)
BOTH = ReplyPlan(speaks=True, writes=True)

TABLE = [
    ("voice", "text", True, SPEAK),
    ("voice", "voice", True, SPEAK),
    ("text", "text", True, WRITE),
    ("text", "voice", True, WRITE),
    ("both", "text", True, BOTH),
    ("both", "voice", True, BOTH),
    ("auto", "voice", True, SPEAK),
    ("auto", "text", True, WRITE),
    *(
        (mode, origin, False, WRITE)
        for mode in ("voice", "text", "both", "auto")
        for origin in ("text", "voice")
    ),
]


@pytest.mark.parametrize(("mode", "origin", "voice_ready", "plan"), TABLE)
def test_decision_table(mode, origin, voice_ready, plan):
    assert reply_plan(mode, origin, voice_ready) == plan


def test_table_covers_all_sixteen_cases():
    assert len({(m, o, r) for m, o, r, _ in TABLE}) == 16
