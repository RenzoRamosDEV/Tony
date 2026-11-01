from pathlib import Path


def processes_mentioning(marker: str) -> list[int]:
    """PIDs whose command line contains `marker` (Linux /proc)."""
    pids = []
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if marker.encode() in cmdline.read_bytes():
                pids.append(int(cmdline.parent.name))
        except OSError:
            continue
    return pids
