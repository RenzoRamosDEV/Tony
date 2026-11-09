## Why

Four reliability gaps remain after the core-loop work: MCP recovery retries never run for probe managers because they exit right after the first attempt; MCP servers connect one after another, so N dead servers delay startup by N × 30 s; music playback searches twice (so it can play a different recording than the one the user approved); and audio-device selection silently falls back to the default device.

## What Changes

- Probe managers (startup probe and config-reload probe) stay open until each failing server recovers, its retries are exhausted, a newer probe supersedes them, or the app shuts down.
- `McpManager` connects servers concurrently (at most 4 at once), each connection opened and closed by its own task; the tool catalog keeps declaration order.
- `music_play`/`music_queue` reuse the track already resolved by `music_search` when the query equals the title it returned (valid 10 minutes, at most 20 tracks); when the cached stream URL has expired they re-resolve and only accept a result with the same title.
- Audio-device selection validates the device kind, matches by exact name as before plus a case-insensitive/trimmed fallback, and fills the existing `input_fallback_warning` / `output_fallback_warning` fields when the default device is used instead of the requested one.
- Nothing is removed or renamed; tool names, arguments and event shapes are unchanged.

## Capabilities

### New Capabilities
- `music-playback`: playing exactly the track that was found and approved.

### Modified Capabilities
- `mcp-connections`: probes keep background recovery alive; concurrent startup with deterministic catalog.
- `audio-devices`: selection honesty (kind validation, tolerant name match, fallback warnings).

## Impact

- Code: `tony/core/mcp/manager.py`, `tony/core/orchestrator/runtime.py` (`_probe`), `tony/core/config/reload.py` (`mcp_probe`), `tony/core/music/player.py`, `tony/core/voice/engines/sounddevice_io.py`, `tony/core/voice/service.py`, `tony/core/orchestrator/runtime.py` (`_set_audio_device`).
- Events: none changed (existing warning fields get populated). Dependencies: none.
