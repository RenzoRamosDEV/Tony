"""Immutable catalog of the MCP tools an agent may call."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Protocol


class McpToolLike(Protocol):
    """The subset of mcp.types.Tool the catalog reads."""

    name: str
    description: str | None
    input_schema: dict[str, Any]
    annotations: Any


@dataclass(frozen=True)
class ToolRef:
    server: str
    name: str
    qualified: str
    description: str
    input_schema: dict[str, Any]
    destructive: bool
    needs_confirm: bool


@dataclass(frozen=True)
class ToolCatalog:
    refs: tuple[ToolRef, ...] = ()
    _index: Mapping[str, ToolRef] = field(default_factory=dict, repr=False, compare=False)
    conflicts: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        tools_by_server: Mapping[str, Iterable[McpToolLike]],
        allow: list[str] | None,
        confirm: list[str],
    ) -> ToolCatalog:
        candidates = (
            _to_ref(server, tool, confirm)
            for server, tools in tools_by_server.items()
            for tool in tools
            if _is_allowed(f"{server}.{tool.name}", allow)
        )
        index: dict[str, ToolRef] = {}
        conflicts: list[str] = []
        for ref in candidates:
            if ref.qualified in index:
                conflicts.append(_conflict_message(index[ref.qualified], ref))
            else:
                index[ref.qualified] = ref
        return cls(tuple(index.values()), index, tuple(conflicts))

    @classmethod
    def empty(cls) -> ToolCatalog:
        return cls()

    def get(self, qualified: str) -> ToolRef | None:
        return self._index.get(qualified)

    def qualified_names(self) -> list[str]:
        return [ref.qualified for ref in self.refs]

    def servers(self) -> dict[str, list[ToolRef]]:
        grouped: dict[str, list[ToolRef]] = {}
        for ref in self.refs:
            grouped.setdefault(ref.server, []).append(ref)
        return grouped

    def __contains__(self, qualified: object) -> bool:
        return qualified in self._index

    def __iter__(self) -> Iterator[ToolRef]:
        return iter(self.refs)

    def __len__(self) -> int:
        return len(self.refs)


def _is_allowed(qualified: str, allow: list[str] | None) -> bool:
    if allow is None:
        return True
    return any(fnmatchcase(qualified, pattern) for pattern in allow)


def _conflict_message(kept: ToolRef, dropped: ToolRef) -> str:
    return (
        f"{kept.qualified}: se ignora la tool '{dropped.name}' del servidor '{dropped.server}' "
        f"porque colisiona con la tool '{kept.name}' del servidor '{kept.server}'"
    )


def _to_ref(server: str, tool: McpToolLike, confirm: list[str]) -> ToolRef:
    qualified = f"{server}.{tool.name}"
    destructive = bool(getattr(tool.annotations, "destructive_hint", None))
    return ToolRef(
        server=server,
        name=tool.name,
        qualified=qualified,
        description=tool.description or "",
        input_schema=dict(tool.input_schema),
        destructive=destructive,
        needs_confirm=destructive or qualified in confirm,
    )
