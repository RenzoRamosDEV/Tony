import fcntl
import json
import os
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tony.core.config.errors import DefinitionError
from tony.core.loader.agent_md import split_frontmatter
from tony.core.loader.tool_json import agent_folder, parse_json, parse_tool_spec, tool_file

GUARD_ROLE = "guard"
LOCK_SUFFIX = ".lock"
TEMP_SUFFIX = ".tmp"


def add_server(
    root: Path,
    key: str,
    name: str,
    entry: dict[str, Any],
    *,
    native_tools: Collection[str],
    lock_timeout: float = 5.0,
    poll: float = 0.05,
) -> str:
    """Add one MCP server to an agent's `tool.json` under an exclusive lock, atomically.

    Returns the written file relative to `root`; on any error the file is left untouched.
    """
    folder = agent_folder(key)
    if not (root / folder).is_dir():
        raise DefinitionError(folder, None, f"agent folder {folder} does not exist")
    if _is_guard(root, folder):
        raise DefinitionError(folder, None, "a guard agent has no tools")
    file = tool_file(key)
    path = root / file
    if not path.is_file():
        raise DefinitionError(file, None, f"missing file {file}")
    with _locked(root, f"{file}{LOCK_SUFFIX}", lock_timeout, poll):
        data = parse_json(path.read_text(encoding="utf-8"), file)
        servers = data.setdefault("mcpServers", {})
        if name in servers:
            raise DefinitionError(
                file, f"mcpServers.{name}", f"server '{name}' already exists in {file}"
            )
        servers[name] = entry
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        parse_tool_spec(text, file=file, native_tools=native_tools)
        _replace(path, text)
    return file


def _is_guard(root: Path, folder: str) -> bool:
    agent_md = root / folder / "agent.md"
    if not agent_md.is_file():
        return False
    try:
        frontmatter, _ = split_frontmatter(agent_md.read_text(), str(agent_md))
    except DefinitionError:
        return False
    return frontmatter.get("role") == GUARD_ROLE


@contextmanager
def _locked(root: Path, lock_file: str, timeout: float, poll: float) -> Iterator[None]:
    # flock is released by the kernel when the process dies, so no stale lock survives.
    with open(root / lock_file, "a") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DefinitionError(
                        lock_file, None, f"could not lock {lock_file} within {timeout:g} s"
                    ) from None
                time.sleep(poll)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _replace(path: Path, text: str) -> None:
    temp = path.with_name(f"{path.name}{TEMP_SUFFIX}")
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
