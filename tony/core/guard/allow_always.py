import os
import tempfile
from pathlib import Path

import yaml

from tony.core.guard.evaluate import rule_matches
from tony.core.guard.policy import Policy, policy_file

ALLOW_ALWAYS_PREFIX = "user-always/"


def allow_always_id(tool: str) -> str:
    return f"{ALLOW_ALWAYS_PREFIX}{tool}"


def offers_allow_always(policy: Policy, tool: str) -> bool:
    """«Permitir siempre» is offered only if no deny rule pattern matches the tool, whatever its
    `when` conditions: a blanket allow placed first would otherwise override that deny."""
    return not any(rule.verdict == "deny" and rule_matches(rule, tool) for rule in policy.rules)


def insert_allow_always(root: Path, guard: str, tool: str) -> None:
    """Put an allow rule for `tool` first in the guard's policy, replacing the file atomically.

    The rewritten file is validated before it replaces the original; on any failure the
    original stays untouched. PyYAML drops comments, which is accepted.
    """
    path = root / policy_file(guard)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = data.setdefault("rules", [])
    rule_id = allow_always_id(tool)
    if any(isinstance(rule, dict) and rule.get("id") == rule_id for rule in rules):
        return
    rules.insert(0, {"match": tool, "verdict": "allow", "id": rule_id})
    Policy.model_validate(data)
    _replace(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def _replace(path: Path, text: str) -> None:
    descriptor, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
