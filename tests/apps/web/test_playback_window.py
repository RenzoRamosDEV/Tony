"""PlaybackWindow: while Tony's audio is (estimated to be) playing (specs/voice-input)."""

from __future__ import annotations

import pytest

from tests.fakes.clock import FakeClock
from tony.apps.web.playback_window import PlaybackWindow


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(start=100.0)


def window(clock: FakeClock) -> PlaybackWindow:
    return PlaybackWindow(clock.monotonic)


def test_closed_until_tts_start_and_open_after_it(clock: FakeClock) -> None:
    playback = window(clock)
    assert not playback.speaking()

    playback.started("m-2")

    assert playback.speaking()


@pytest.mark.parametrize("close", ["stopped", "cancelled"])
def test_playback_stopped_or_cancelled_closes_it(clock: FakeClock, close: str) -> None:
    playback = window(clock)
    playback.started("m-2")
    playback.chunk("m-2", 1_000)

    getattr(playback, close)("m-2")

    assert not playback.speaking()


async def test_without_notice_it_closes_two_seconds_after_the_estimated_end(
    clock: FakeClock,
) -> None:
    playback = window(clock)
    playback.started("m-2")
    await clock.advance(0.5)
    playback.chunk("m-2", 1_000)
    playback.chunk("m-2", 2_000)
    playback.ended("m-2")

    await clock.advance(4.999)
    assert playback.speaking()
    await clock.advance(0.001)
    assert not playback.speaking()


async def test_the_deadline_counts_from_the_first_chunk_not_the_start(clock: FakeClock) -> None:
    playback = window(clock)
    playback.started("m-2")
    await clock.advance(10)
    assert playback.speaking()

    playback.chunk("m-2", 100)
    await clock.advance(2.1)

    assert not playback.speaking()


def test_an_end_without_chunks_closes_it(clock: FakeClock) -> None:
    playback = window(clock)
    playback.started("m-2")

    playback.ended("m-2")

    assert not playback.speaking()


async def test_overlapping_messages_keep_it_open_until_the_last_one_stops(
    clock: FakeClock,
) -> None:
    playback = window(clock)
    playback.started("m-1")
    playback.chunk("m-1", 1_000)
    playback.started("m-2")
    playback.chunk("m-2", 5_000)

    playback.stopped("m-2")
    assert playback.speaking()
    playback.stopped("m-1")
    assert not playback.speaking()
    playback.stopped("m-9")
    playback.chunk("m-9", 1_000)
    assert not playback.speaking()


async def test_an_expired_message_does_not_hide_a_live_one(clock: FakeClock) -> None:
    playback = window(clock)
    playback.started("m-1")
    playback.chunk("m-1", 100)
    await clock.advance(1)
    playback.started("m-2")
    await clock.advance(5)

    assert playback.speaking()
    playback.cancelled("m-2")
    assert not playback.speaking()
