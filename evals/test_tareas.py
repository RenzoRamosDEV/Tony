"""Task evals: the worker over the fake filesystem MCP (fixtures) or the real model."""

from __future__ import annotations

import pytest

from evals.conftest import load_spec, run_task_eval, task_evals
from tony.core.evals.assertions import check_task

EVALS = task_evals()


@pytest.mark.evals
@pytest.mark.parametrize("eval", EVALS, ids=[e.id for e in EVALS])
async def test_task(eval, settings, agents_dir, env) -> None:
    spec = load_spec(agents_dir, eval.agent, settings, env)

    result, events = await run_task_eval(eval, spec, settings)

    failures = check_task(result, events.events, eval.expect)
    assert failures == [], f"{eval.id}: " + "; ".join(failures)
