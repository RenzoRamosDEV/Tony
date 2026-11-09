## 1. Probe recovery (mcp-connections)
- [x] 1.1 Write failing tests: `wait_settled` returns after recovery/exhaustion; startup probe and reload probe keep retrying; superseded probe cancelled; no tasks left
- [x] 1.2 Implement `wait_settled`, update `runtime._probe` and `reload.mcp_probe`, track probes per (key, server)

## 2. Concurrent startup (mcp-connections)
- [x] 2.1 Write failing tests: 4 slow servers start in < one timeout window (fake clock), declaration order, one failure isolated, cleanup on cancel
- [x] 2.2 Implement bounded concurrent connection tasks with per-task ownership

## 3. Music approved track (music-playback)
- [x] 3.1 Write failing tests: reuse after search, different query searches, TTL expiry refresh same/different title, cache size 20
- [x] 3.2 Implement `ResolvedTracks` and wire into `MusicPlayer`

## 4. Device selection (audio-devices)
- [x] 4.1 Write failing tests: kind filtering, exact then normalized match, missing device warning for input and output, default produces no warning
- [x] 4.2 Implement resolution result, propagate warnings through `VoiceService` and `runtime`

## 5. Verification
- [x] 5.1 Run the full suite and mutation testing on the diff (>95 %, abort at 3 min)
