import sys
from pathlib import Path

FAKE_FS_SERVER = Path(__file__).with_name("fake_fs_server.py")


def fake_fs_entry(root_arg: str, **extra) -> dict:
    return {"command": sys.executable, "args": [str(FAKE_FS_SERVER), root_arg], **extra}


FAKE_SHELL_SERVER = Path(__file__).with_name("fake_shell_server.py")


def fake_shell_entry() -> dict:
    return {"command": sys.executable, "args": [str(FAKE_SHELL_SERVER)]}
