"""Replaces itself with a connector whose environment is exactly the one it is handed.

The MCP SDK always merges its default variables into the spawned process, so the
isolated environment travels in ``TONY_ISOLATED_ENV`` and is applied here by exec.
Stdlib only: it runs under ``python -I`` before anything of Tony is importable.
"""

import json
import os
import sys

ENV_VARIABLE = "TONY_ISOLATED_ENV"
NOT_FOUND = 127


def main(argv: list[str]) -> int:
    command, *args = argv
    environment = json.loads(os.environ[ENV_VARIABLE])
    try:
        os.execvpe(command, [command, *args], environment)
    except OSError as error:
        print(f"tony: cannot launch '{command}': {error.strerror}", file=sys.stderr)
        return NOT_FOUND


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
