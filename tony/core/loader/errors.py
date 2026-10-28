"""Errors raised while loading agent definitions."""

from __future__ import annotations


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
