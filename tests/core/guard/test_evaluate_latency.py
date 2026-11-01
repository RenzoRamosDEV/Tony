import time

from tests.core.guard.shipped_policy import SHIPPED_POLICY_DATA
from tony.core.guard.evaluate import evaluate
from tony.core.guard.policy import Policy

CALLS = [
    ("filesystem.read_file", {"path": "~/notas/a.md"}),
    ("filesystem.write_file", {"path": "/tmp/a.md", "content": "x" * 500}),
    ("shell.run", {"command": "ls -la /var/log"}),
    ("github.create_issue", {"title": "t", "body": {"nested": ["a", "b", {"c": "d"}]}}),
    ("unknown.tool", {"paths": ["~/notas/a.md", "~/proyectos/b.md"]}),
]


def test_mean_evaluation_under_five_milliseconds():
    policy = Policy.model_validate(SHIPPED_POLICY_DATA)
    runs = 1000

    start = time.perf_counter()
    for index in range(runs):
        tool, args = CALLS[index % len(CALLS)]
        evaluate(policy, tool, args)
    mean = (time.perf_counter() - start) / runs

    assert mean < 0.005
