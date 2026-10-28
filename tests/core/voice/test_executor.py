"""VoiceExecutor: a two-thread pool that keeps the event loop responsive (specs/voice-engines)."""

from __future__ import annotations

import asyncio
import threading
import time

from tony.core.voice.executor import VoiceExecutor


async def test_run_executes_in_a_named_voice_thread() -> None:
    executor = VoiceExecutor()
    try:
        name = await executor.run(lambda: threading.current_thread().name)
        doubled = await executor.run(lambda x: x * 2, 21)
    finally:
        executor.close()

    assert name.startswith("tony-voice")
    assert doubled == 42


async def test_never_more_than_two_tasks_run_concurrently() -> None:
    executor = VoiceExecutor()
    lock = threading.Lock()
    running = 0
    peak = 0

    def work() -> None:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1

    try:
        await asyncio.gather(*(executor.run(work) for _ in range(5)))
    finally:
        executor.close()

    assert peak == 2


async def test_the_loop_answers_while_a_task_blocks_a_thread() -> None:
    executor = VoiceExecutor()
    order: list[str] = []

    async def hello() -> None:
        await asyncio.sleep(0)
        order.append("hello")

    async def slow() -> None:
        await executor.run(time.sleep, 0.2)
        order.append("slow")

    try:
        await asyncio.gather(slow(), hello())
    finally:
        executor.close()

    assert order == ["hello", "slow"]


async def test_close_does_not_wait_for_pending_work() -> None:
    executor = VoiceExecutor()
    started = threading.Event()
    pending = asyncio.ensure_future(executor.run(lambda: (started.set(), time.sleep(0.3))))
    await asyncio.get_running_loop().run_in_executor(None, started.wait)

    before = time.monotonic()
    executor.close()
    elapsed = time.monotonic() - before

    assert elapsed < 0.1
    await asyncio.gather(pending, return_exceptions=True)


async def test_review05_finding_7_a_lane_stays_busy_until_its_cancelled_work_really_ends() -> None:
    executor = VoiceExecutor()
    started, release = threading.Event(), threading.Event()
    order: list[str] = []

    def blocked() -> None:
        started.set()
        release.wait(timeout=5)
        order.append("first ended")

    def second() -> None:
        order.append("second started")

    try:
        first = asyncio.ensure_future(executor.run_serial("tts", blocked))
        await asyncio.get_running_loop().run_in_executor(None, started.wait)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        follower = asyncio.ensure_future(executor.run_serial("tts", second))
        other_lane = await asyncio.wait_for(executor.run(lambda: "stt"), 1)
        await asyncio.sleep(0.05)
        waiting = list(order)
        release.set()
        await asyncio.wait_for(follower, 1)
    finally:
        executor.close()

    assert other_lane == "stt"
    assert waiting == []
    assert order == ["first ended", "second started"]
