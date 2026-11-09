import json
import sys
from collections.abc import Mapping

from mcp.client.stdio import StdioServerParameters

from tony.core.loader.tool_json import McpServer
from tony.core.mcp import isolated_exec

BASE_VARIABLES = ("PATH", "HOME", "LANG", "LC_ALL")


def isolated_environment(server: McpServer, host: Mapping[str, str]) -> dict[str, str]:
    names = [*BASE_VARIABLES, *server.isolation.env_allow]
    inherited = {name: host[name] for name in names if name in host}
    return {**inherited, **server.env}


def isolated_parameters(
    command: str, server: McpServer, host: Mapping[str, str]
) -> StdioServerParameters:
    environment = json.dumps(isolated_environment(server, host))
    return StdioServerParameters(
        command=sys.executable,
        args=["-I", isolated_exec.__file__, command, *server.args],
        env={isolated_exec.ENV_VARIABLE: environment},
    )
