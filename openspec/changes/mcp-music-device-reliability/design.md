## Context

Observed: `McpManager.__aenter__` starts servers in a `for` loop; failed servers spawn `_retry` tasks that are cancelled in `__aexit__`. `runtime._probe` and `reload.mcp_probe` use `async with manager: pass`, so retries are cancelled immediately. `MusicPlayer.search/play/queue` each call the resolver; `Track.url` is an expiring stream URL. `_resolve_device` in `sounddevice_io.py` matches exact name over all devices (ignoring kind) and returns `None` silently; `_publish_audio_devices` already accepts fallback warnings that nothing fills.

## Decisions

1. **Settle signal in the manager.** Each retry task owns an `asyncio.Event`; the manager exposes `wait_settled()` (all retry tasks finished backoff: recovered or exhausted). A recovered retry keeps its connection open until the manager exits (as today). Probes do `async with manager: await manager.wait_settled()`. Shutdown cancels the probe tasks (tracked by existing sets). The reload keeps a dict `(key, server) -> task` and cancels the previous task when scheduling a new one.
2. **Concurrent connect.** Startup uses an `asyncio.Semaphore(4)` and one task per server, each running `_start` and keeping its own `AsyncExitStack` open until exit via an exit event (anyio scope ownership: the task that opens a connection closes it). Results are merged into `tools` in declaration order after all tasks report. Failure of one task does not cancel the others; `BaseException` (cancellation) cancels all.
3. **Track cache by title.** A small in-memory `ResolvedTracks` (max 20, TTL 10 min, injectable clock) keyed by the exact title returned by `search`. `play`/`queue` check it first. After TTL expiry the title is re-resolved and accepted only on equal title. A title key (instead of a new `pista` argument) keeps tool schemas, the Edith policy and the skill unchanged.
4. **Device resolution.** `_resolve_device` filters PortAudio devices by `max_input_channels`/`max_output_channels` for the kind, matches exact then normalized, and returns a result object `(index | None, matched: bool)`. `VoiceService.set_*_device` reports `matched`; the runtime passes the warning to `_publish_audio_devices` after `SetAudioDevice`.

## Risks / Trade-offs

- Anyio context ownership → connection tasks open and close in the same task; covered by tests with fake connections.
- Concurrency raising memory/process counts at startup → bounded to 4.
- Title collisions in cache → exact-title key plus equality check on refresh.
- Deviation from "handle" wording: the title is the user-approved identity, so no new tool argument is needed.
