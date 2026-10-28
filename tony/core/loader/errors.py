"""Errors raised while loading agent definitions."""

from __future__ import annotations

from pydantic import ValidationError


class AgentLoadError(Exception):
    """An agent folder could not be loaded; carries the agent name and reason."""

    def __init__(self, agent: str, message: str) -> None:
        super().__init__(f"{agent}: {message}")
        self.agent = agent
        self.message = message


class MissingEnvVar(Exception):
    """A ${VAR} placeholder referenced a variable that is not defined."""

    def __init__(self, var: str, server: str | None = None) -> None:
        where = f" (servidor {server})" if server else ""
        super().__init__(f"variable de entorno {var} no definida{where}")
        self.var = var
        self.server = server


def format_validation_error(exc: ValidationError) -> str:
    """`field.path: message` per error, joined by `; `, without pydantic's prefix."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts)
