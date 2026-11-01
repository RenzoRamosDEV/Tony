import re
from collections.abc import Iterable, Mapping
from typing import Any

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
MASK = "***"


class UndefinedVariableError(Exception):
    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(f"undefined variable {variable}")


def resolve_placeholders(value: Any, variables: Mapping[str, str]) -> tuple[Any, set[str]]:
    used: set[str] = set()

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise UndefinedVariableError(name)
        used.add(variables[name])
        return variables[name]

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return _PLACEHOLDER.sub(substitute, node)
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        return node

    return walk(value), used


class SecretMasker:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets: set[str] = set()
        self.register(secrets)

    def register(self, secrets: Iterable[str]) -> None:
        self._secrets.update(secret for secret in secrets if secret)

    def mask(self, text: str) -> str:
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, MASK)
        return text

    def mask_json(self, data: Any) -> Any:
        if isinstance(data, str):
            return self.mask(data)
        if isinstance(data, list):
            return [self.mask_json(item) for item in data]
        if isinstance(data, dict):
            return {self.mask(key): self.mask_json(item) for key, item in data.items()}
        return data
