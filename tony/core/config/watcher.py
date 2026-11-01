import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from watchfiles import Change, awatch

from tony.core.config.reload import classify


def config_filter(root: Path, guard: str) -> Callable[[Change, str], bool]:
    def accept(change: Change, path: str) -> bool:
        return classify(root, guard, Path(path)) is not None

    return accept


async def watch_config(
    root: Path, guard: str, stop: asyncio.Event, *, debounce: int = 1600, step: int = 50
) -> AsyncIterator[set[Path]]:
    """Batches of changed `tool.json` and guard `policy.yaml` paths until `stop` is set.

    watchfiles reports resolved paths, so they are mapped back under `root` as given.
    """
    resolved = root.resolve()
    async for changes in awatch(
        resolved / "agents",
        watch_filter=config_filter(resolved, guard),
        stop_event=stop,
        debounce=debounce,
        step=step,
    ):
        yield {root / Path(path).relative_to(resolved) for _, path in changes}
