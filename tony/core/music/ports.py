from dataclasses import dataclass
from typing import Protocol


class MusicError(Exception):
    """A failure the user can act on; the message is shown as is."""


@dataclass(frozen=True)
class Track:
    title: str
    url: str


@dataclass(frozen=True)
class Status:
    title: str
    paused: bool
    volume: int
    position: float | None
    duration: float | None


class Resolver(Protocol):
    def resolve(self, query: str) -> Track: ...


class PlayerBackend(Protocol):
    def load(self, track: Track) -> None: ...
    def append(self, track: Track) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def next(self) -> None: ...
    def previous(self) -> None: ...
    def set_volume(self, level: int) -> None: ...
    def status(self) -> Status | None: ...
    def stop(self) -> None: ...
