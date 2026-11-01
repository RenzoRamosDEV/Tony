from pathlib import Path

import pytest
import yaml

from tony.core.guard.evaluate import evaluate
from tony.core.guard.policy import Policy, load_policy

REPO = Path(__file__).resolve().parents[3]
EVALS = REPO / "evals" / "politica.yaml"
FAKE_HOME = "/home/renzo"


def load_cases():
    return yaml.safe_load(EVALS.read_text()) if EVALS.is_file() else []


CASES = load_cases()


def with_extra_rules(shipped: Policy, extra_rules: list) -> Policy:
    data = shipped.model_dump(mode="json")
    data["rules"] = [*extra_rules, *data["rules"]]
    return Policy.model_validate(data)


def test_eval_file_has_enough_cases_covering_every_verdict():
    assert len(CASES) >= 20
    assert {case["expected"] for case in CASES} == {"allow", "confirm", "deny"}


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{index}-{case['tool']}" for index, case in enumerate(CASES)]
)
def test_case_verdict_matches_shipped_policy(case, monkeypatch):
    monkeypatch.setenv("HOME", FAKE_HOME)
    policy = with_extra_rules(load_policy(REPO, "edith"), case.get("extra_rules", []))

    verdict = evaluate(policy, case["tool"], case.get("args", {}))

    assert verdict.verdict == case["expected"]
