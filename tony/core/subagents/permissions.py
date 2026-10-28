"""Permissions of a subagent as the intersection with its parent's tool configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from tony.core.loader import HttpServer, StdioServer, ToolConfig
from tony.core.mcp.catalog import ToolCatalog

ServerSpec = StdioServer | HttpServer
NESTED_SERVER_WARNING = (
    "el subagente declara el servidor MCP '{server}' pero su padre ya es un subagente; se ignora"
)


@dataclass
class ChildPolicy:
    servers: dict[str, ServerSpec]
    new_servers: list[str] = field(default_factory=list)
    allow_parent: list[str] | None = None
    allow_child: list[str] | None = None
    confirm: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def child_policy(parent: ToolConfig, child: ToolConfig, parent_is_subagent: bool) -> ChildPolicy:
    """Parent servers always win; the child may add servers only under a top-level parent."""
    servers: dict[str, ServerSpec] = dict(parent.mcpServers)
    new_servers: list[str] = []
    warnings: list[str] = []
    for name, server in child.mcpServers.items():
        if name in servers:
            continue
        if parent_is_subagent:
            warnings.append(NESTED_SERVER_WARNING.format(server=name))
            continue
        servers[name] = server
        new_servers.append(name)
    confirm = list(parent.confirm) + [c for c in child.confirm if c not in parent.confirm]
    return ChildPolicy(servers, new_servers, parent.allow, child.allow, confirm, warnings)


def effective_catalog(parent_catalog: ToolCatalog, policy: ChildPolicy) -> ToolCatalog:
    """The parent's real tools narrowed by the child's allow, with the union of confirms."""
    return parent_catalog.restrict(policy.allow_child).with_confirm(policy.confirm)
