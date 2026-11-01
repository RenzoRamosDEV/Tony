import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER = Path(__file__).with_name("fake_fs_server.py")


@asynccontextmanager
async def session_for(root, env=None):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER), str(root)], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def text_of(result):
    return "".join(block.text for block in result.content)


async def test_lists_the_fake_tools(tmp_path):
    async with session_for(tmp_path) as session:
        listed = await session.list_tools()

    assert {tool.name for tool in listed.tools} == {
        "list_directory",
        "read_file",
        "sleep",
        "echo_env",
        "write_file",
        "delete_file",
    }


async def test_lists_and_reads_files_under_root(tmp_path):
    (tmp_path / "a.md").write_text("hola")
    (tmp_path / "b.md").write_text("adios")

    async with session_for(tmp_path) as session:
        listing = await session.call_tool("list_directory", {"path": "."})
        content = await session.call_tool("read_file", {"path": "a.md"})

    assert text_of(listing) == "a.md\nb.md"
    assert text_of(content) == "hola"


async def test_rejects_path_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.md").write_text("nope")

    async with session_for(root) as session:
        result = await session.call_tool("read_file", {"path": "../secret.md"})

    assert result.is_error
    assert "nope" not in text_of(result)


async def test_missing_file_is_error(tmp_path):
    async with session_for(tmp_path) as session:
        result = await session.call_tool("read_file", {"path": "nada.md"})

    assert result.is_error and "nada.md" in text_of(result)


async def test_echo_env_returns_variable_value(tmp_path):
    async with session_for(tmp_path, env={"TOKEN": "s3cr3t"}) as session:
        result = await session.call_tool("echo_env", {"name": "TOKEN"})

    assert text_of(result) == "s3cr3t"


async def test_writes_and_deletes_files_under_root(tmp_path):
    async with session_for(tmp_path) as session:
        written = await session.call_tool("write_file", {"path": "n.md", "content": "hola"})
        content = (tmp_path / "n.md").read_text()
        deleted = await session.call_tool("delete_file", {"path": "n.md"})

    assert (text_of(written), content) == ("written n.md", "hola")
    assert text_of(deleted) == "deleted n.md"
    assert not (tmp_path / "n.md").exists()


async def test_write_and_delete_reject_path_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "keep.md").write_text("x")

    async with session_for(root) as session:
        written = await session.call_tool("write_file", {"path": "../evil.md", "content": "x"})
        deleted = await session.call_tool("delete_file", {"path": "../keep.md"})

    assert written.is_error and deleted.is_error
    assert not (tmp_path / "evil.md").exists()
    assert (tmp_path / "keep.md").exists()


async def test_delete_missing_file_is_error(tmp_path):
    async with session_for(tmp_path) as session:
        result = await session.call_tool("delete_file", {"path": "nada.md"})

    assert result.is_error and "nada.md" in text_of(result)
