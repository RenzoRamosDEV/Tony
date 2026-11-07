# Design: Audio device settings + persistent Edith unlock

Status: approved (decisions finalized in brainstorming conversation, 2026-11-06)
Scope: two independent features bundled into one design pass because both touch
config persistence, the desktop bridge protocol, and runtime/orchestrator wiring.

## Intent and why

**Audio settings.** Today `SoundDeviceInput`/`SoundDeviceOutput`
(`tony/core/voice/engines/sounddevice_io.py`) always use the system default
device — no way to pick a different mic or speaker. Users with multiple audio
devices need to choose, and the choice must survive restarts and reboots.

**Persistent unlock.** `EdithSession` (`tony/core/guard/session.py`) only
remembers unlock state in memory. Every process restart forces re-entry of the
PIN even if the idle-timeout window (`Auth.lock_after_min`) hasn't elapsed.
This is friction without security benefit, since the in-memory relock logic
already defines what "still within the window" means — restarting the process
shouldn't reset that clock to zero.

## Goals

- Let the user pick input/output audio devices by name, live-switchable, from
  the desktop UI, persisted across restarts.
- Fall back safely to system default when a persisted device disappears.
- Remember "still unlocked" across an app restart, within the same idle
  window `touch()` already enforces in-memory today.
- Preserve the PIN-hash-only invariant: no PIN value is ever persisted
  anywhere, before or after this change.

## Non-goals

- No UI for renaming/aliasing devices, no multi-channel selection, no sample
  rate / buffer size tuning exposed to the user.
- No OS keychain, secure-enclave, or credential-manager integration for the
  unlock expiry — a plain local file is sufficient since no secret is stored.
- No change to `PinStore`'s hashing, back-off constants, or the PIN entry UI
  flow beyond what's needed to wire the new initial-state check.

## Anti-goals

- Do not weaken the PIN hash invariant (`PinStore` stores only an argon2
  hash) to make this easier.
- Do not persist device selection by numeric index — unstable across
  reboots/hot-plug, explicitly rejected.
- Do not turn the settings overlay into a permanently docked panel like
  Activity/Edith — it must follow the `PinOverlay` modal pattern, so it never
  competes for permanent screen space.

## Constraints

- `VoiceSettings` is a strict pydantic model (`extra="forbid"`); new fields
  must be added there deliberately, not accreted elsewhere.
- `Command`/`CoreEvent` are closed discriminated unions on both sides
  (Python `Annotated[... , Field(discriminator="type")]` TypeAdapter in
  `commands.py`; TS union in `bridge/types.ts`) — both sides must be extended
  in lockstep, mirroring the existing 1:1 field shape convention.
- `config/edith.lock` (PIN hash) and any new unlock-expiry file must stay
  out of git, following the existing `.gitignore` local-only-file convention
  (`config/edith.lock`, `memory/*.sqlite*`, `memory/settings.json`, etc.).
- Device enumeration (`sounddevice.query_devices()`) is a Python-only
  concern; the web front never talks to `sounddevice` directly, same as
  today's VAD/STT/TTS split.
- Live device switching must not require a full voice-service restart —
  only the open `SoundDeviceInput` stream (if any) is affected.

## Approaches considered

### Audio device identification: by name vs. by index
- **Chosen:** persist by device name (string), resolve to an index at
  `sounddevice.query_devices()` time on each open/play call.
- **Rejected — persist by index:** indices are reassigned by the OS across
  reboots and hot-plug events, so a persisted index can silently point at the
  wrong device. Rejected for instability.

### Persistent unlock: expiry file vs. OS keychain
- **Chosen:** plain local file with an "unlocked until" timestamp, refreshed
  on each message exactly like `touch()` does in memory, gitignored.
- **Rejected — OS keychain/secure storage:** no secret is being stored (just
  a timestamp), so keychain integration is unnecessary dependency weight and
  cross-platform complexity for no security gain. Rejected as overkill.

### Persistent unlock: where the expiry lives
- **Chosen:** separate file from `config/edith.lock`, so the PIN-hash file's
  format and lifecycle are never touched by this feature.
- **Rejected — reuse/extend `edith.lock`:** would mix a mutable, frequently
  rewritten runtime value into the same file as the security-sensitive PIN
  hash, increasing the risk surface of that file and complicating `PinStore`.
  Rejected to keep the hash file single-purpose and untouched.

## Decided design

### Feature 1 — Audio device settings

**Config (`tony/core/config/settings.py`, `VoiceSettings`):**

```
class VoiceSettings(_Strict):
    stt: str = "faster-whisper/small"
    vad: str = "silero"
    tts_default: str = "kokoro/em_alex"
    input_device: str | None = None   # device name; None = system default
    output_device: str | None = None  # device name; None = system default
```

`None` means "system default" for both — matches current behavior exactly
when unset, so existing configs need no migration.

**Python modules:**

- `tony/core/voice/engines/sounddevice_io.py`
  - `SoundDeviceInput.__init__(self, device: str | None = None)` — stores the
    device name; `open()` resolves it to an index via
    `sounddevice.query_devices()` immediately before opening the stream
    (fresh lookup each time, so a just-replugged device is found).
  - Add `SoundDeviceInput.set_device(self, device: str | None) -> None`:
    updates the stored device name; if a stream is currently open, closes it
    and reopens it on the new device with the same `on_frame` callback (the
    runtime must keep the callback accessible across the swap — store it on
    `self` in `open()`).
  - `SoundDeviceOutput.__init__(self, device: str | None = None)` — stores
    the device name; `play()` resolves it to an index and passes
    `device=<index>` to `sounddevice.play(...)`. No persistent stream, so
    `set_device()` on output just updates the stored name for the next
    `play()` call — no live teardown needed.
  - Add a small resolver helper, e.g. `_resolve_device(name: str | None,
    kind: Literal["input", "output"]) -> int | None`: returns `None` for
    "system default" or when the named device is no longer present (see
    fallback behavior below), else the matching device's index from
    `sounddevice.query_devices()`.
- `tony/core/voice/engines/loader.py` — `build_engines` passes
  `settings.input_device` / `settings.output_device` into the
  `SoundDeviceInput` / `SoundDeviceOutput` constructors.
- `tony/core/voice/ports.py` — extend the `AudioInput` protocol with
  `set_device(self, device: str | None) -> None` (output's `set_device` can
  be a plain attribute assignment but should also be added to `AudioOutput`
  for symmetry and testability).
- New module, e.g. `tony/core/voice/devices.py`: `list_devices() ->
  tuple[DeviceInfo, ...]` wrapping `sounddevice.query_devices()`, returning a
  small `DeviceInfo(name: str, kind: Literal["input","output"], is_default:
  bool)` per device (a device with both input and output channels appears
  once per kind it supports). This is the single call site for
  `query_devices()`, keeping the dependency isolated and mockable.

**Bridge protocol (new Command/CoreEvent pair):**

`tony/apps/desktop/web/src/bridge/types.ts` / mirrored in
`tony/core/orchestrator/commands.py` and `tony/core/events/core_events.py`:

- New Command (UI → core), requesting the current device list on overlay
  open:
  ```ts
  { type: "list_devices" }
  ```
- New Command (UI → core), applying a selection:
  ```ts
  { type: "set_audio_device"; kind: "input" | "output"; device: string | null }
  ```
  `device: null` means "use system default."
- New CoreEvent (core → UI), answering `list_devices` and also pushed
  proactively whenever a previously-selected device disappears (see
  fallback below):
  ```ts
  interface AudioDevicesEvent extends Base {
    type: "audio_devices";
    input: { name: string; is_default: boolean }[];
    output: { name: string; is_default: boolean }[];
    selected_input: string | null;
    selected_output: string | null;
    input_fallback_warning: string | null;  // set when a saved device vanished
    output_fallback_warning: string | null;
  }
  ```
  Python-side mirror in `core_events.py`: a new `audio_devices(...)` event
  builder function, same `_event(kind, clock, **fields)` pattern as
  `voice_state`/`mcp_status`.
- Python `Command` union (`commands.py`) gains `ListDevices` and
  `SetAudioDevice(_Command)` classes (`kind: Literal["input","output"]`,
  `device: str | None`), added to the `Command` discriminated union and to
  `CoreRuntime._dispatch` in `tony/core/orchestrator/runtime.py`.

**Runtime wiring (`tony/core/orchestrator/runtime.py`):**

- `CoreRuntime` needs a handle to the live `SoundDeviceInput`/
  `SoundDeviceOutput` instances to call `set_device()` on — these currently
  live inside `Engines`, constructed inside `VoiceService`/voice engine
  loading, not held directly by `CoreRuntime`. The builder must thread a
  reference out (e.g. `VoiceService` exposes `set_input_device(name)` /
  `set_output_device(name)` that delegate to the underlying engines) so
  `_dispatch` can call `self.voice.set_input_device(...)` /
  `set_output_device(...)` without reaching into voice-service internals.
- On `SetAudioDevice`, after applying, persist the new value into
  `VoiceSettings` and rewrite `config/tony.yaml` (reuse whatever config-write
  helper exists for live config changes — check `tony/core/config/reload.py`
  / `watcher.py` for the existing live-reload write path; if none exists for
  writing back, add a small `save_config(root, config)` alongside
  `load_config`).
- On `ListDevices`, call `tony.core.voice.devices.list_devices()` and publish
  `audio_devices(...)` with the current `VoiceSettings.input_device` /
  `output_device` as `selected_input`/`selected_output`.

**Unplugged-device fallback (my call, stated explicitly):**

- Resolution happens lazily, at the point of use (`open()` for input,
  `play()` for output), never at startup eagerly validated — this matches
  "apply live" and avoids a separate validation pass.
- If `_resolve_device` can't find the persisted name in the current
  `query_devices()` list, it returns `None` (system default) for that call
  and the engine proceeds with the default device rather than failing the
  turn.
- When this fallback fires, the runtime publishes a fresh `audio_devices`
  event with the relevant `*_fallback_warning` field set to a short message
  (e.g. `"Dispositivo 'X' no disponible; usando predeterminado."`) so the UI
  can show a one-time visible warning without polling.
- The persisted setting in `tony.yaml` is left unchanged (not silently
  cleared) — if the device reappears (replugged), it's used again
  automatically on the next open/play, no user action required.

**Frontend:**

- New component `tony/apps/desktop/web/src/components/AudioSettingsOverlay.tsx`,
  structurally mirroring `PinOverlay.tsx`: a hidden/trigger state (gear-icon
  button) and an open state rendering a `role="dialog" aria-modal="true"`
  card with two `<select>` lists (input, output) populated from the latest
  `audio_devices` event, each option built from `DeviceInfo.name` plus a
  "System default" option mapping to `null`. Selecting an option dispatches
  `set_audio_device`. Fallback warnings render inline per list.
- Wired into `App.tsx` next to `PinOverlay`: a new reducer slice
  (`state/reducer.ts`) holding the latest device list / selection /
  warnings, updated on the `audio_devices` event the same way `pin`/`voice`
  slices are updated today; a gear-icon trigger button placed alongside the
  existing `MicButton`/`ReplyModeSelector` controls; `onCommand={send}` wired
  the same way other panels receive `send`.
- `list_devices` is sent once when the overlay is opened (on trigger click),
  not on every app load, to avoid querying `sounddevice` before it's needed.

### Feature 2 — Persistent Edith unlock

**New file:** `config/edith.session` (my call on the name, per the user's
suggestion) — plain text or minimal JSON containing just an ISO-8601 (or
epoch-seconds) "unlocked until" timestamp. No PIN, no hash, no other state.

**`.gitignore`:** add `config/edith.session` next to the existing
`config/edith.lock` entry.

**`tony/core/guard/pin.py` or a new sibling module** (my call: new module
`tony/core/guard/unlock_expiry.py` to keep `PinStore` untouched, per the
"separate file, separate lifecycle" decision above):

```
class UnlockExpiry:
    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = root / "config/edith.session"
        self._clock = clock

    def is_valid(self) -> bool: ...   # file exists, parses, and now < expiry
    def refresh(self, lock_after_min: int) -> None: ...  # write now + lock_after_min*60
    def clear(self) -> None: ...      # delete the file; no-op if absent
```

Writes use the same atomic temp-file-then-`os.replace` pattern as
`PinStore.set` to avoid partial writes on crash.

**`tony/core/guard/session.py` (`EdithSession`) changes:**

- Constructor gains an optional `expiry: UnlockExpiry | None = None`
  parameter (default `None` preserves current behavior for callers/tests
  that don't pass it).
- Initial-state logic, inserted before the existing `pin_required`/
  `has_valid_lock` branches: if `expiry is not None and auth.pin_required and
  pins.has_valid_lock() and expiry.is_valid()`, initialize
  `self.status = AuthStatus("unlocked", "unlocked", 0)` and seed
  `self._last_message = self._monotonic()` so the idle clock continues from
  "now," not from a stale point — this is a deliberate restart-time choice:
  the exact elapsed idle time before restart is not reconstructed, only
  "was still within the window at last persist" is honored, since that's all
  `touch()`'s in-memory model ever guaranteed anyway.
- `attempt()` on success: call `self._expiry.refresh(self._auth.lock_after_min)`
  if an expiry is configured, mirroring the new `unlocked` state.
  `touch()` on a message while unlocked (no relock triggered): also calls
  `refresh()`, matching "refreshed on each message the same way `touch()`
  already does in memory."

**Exact relock transitions that clear the file (my call, stated explicitly):**

Every path that sets `self.status` to a `locked` state must call
`self._expiry.clear()` if an expiry is configured:
1. `touch()` idle relock (`AuthStatus("locked", "idle", 0)`).
2. `cancel()` (`_lock_conversation_only("cancelled")`).
3. `_lock_conversation_only` for any reason, including the
   `"no_lock_file"` path hit from the constructor or from `attempt()` — if
   the lock file itself goes missing/invalid, any stale session file is
   meaningless and must go too.
4. Exceeding the PIN back-off is not itself a relock from `unlocked` (you
   can only hit back-off while already `locked`), so no separate clear is
   needed there beyond the general rule above — back-off failures never
   touch `self._expiry` either way since the session was never unlocked in
   that attempt sequence. State this explicitly so the builder doesn't
   add an unnecessary clear call on `wrong_pin`/`backoff` — those are no-ops
   for the expiry file.

`attempt()` success (`unlocked`) is the only path that *writes* a fresh
expiry rather than clearing one.

**Wiring in `tony/core/orchestrator/runtime.py`:**

`CoreRuntime._start()` constructs `EdithSession` — change:
```
self.session = EdithSession(
    policy.auth, PinStore(self._root),
    monotonic=self._monotonic,
    expiry=UnlockExpiry(self._root),
)
```
No other call site changes; `SessionGate`, `_unlock`, and all event
publishing stay as-is since they operate on `AuthStatus` values the session
already produces.

## Testing strategy (left to the builder, flagged here per TDD policy)

- `UnlockExpiry`: unit tests for write/read/expired/missing/corrupt-file
  cases, using a fake clock (no real filesystem timing dependency beyond a
  tmp dir).
- `EdithSession`: parametrize existing constructor tests with a fake
  `UnlockExpiry` double to assert (a) restart-unlocked only when
  `is_valid()` is true and lock file is valid and pin required, (b) every
  relock transition calls `clear()` exactly once, (c) `touch()`/`attempt()`
  success call `refresh()` with the configured `lock_after_min`.
- `SoundDeviceInput.set_device`: test via a fake `sounddevice` module/stub
  (per existing project convention — check how `sounddevice_io.py` is
  currently tested) asserting close-then-reopen only when a stream was
  open, and no-op stream state otherwise.
- `_resolve_device`: unit test the "name not found → None + fallback"
  branch directly against a stubbed `query_devices()` return value.
- Command/Event round-trip: extend the existing bridge-protocol test
  (wherever `parse_command` and the TS `Command`/`CoreEvent` unions are
  cross-checked today) to cover `ListDevices`, `SetAudioDevice`, and
  `audio_devices`.

## Risks / follow-ups

- `VoiceService`/`Engines` currently has no handle exposed to `CoreRuntime`
  for live device swap — the exact threading of `set_input_device`/
  `set_output_device` through `VoiceService` is sketched above but its
  current internals (`tony/core/voice/service.py`) were not read in this
  pass; the builder should confirm `VoiceService`'s shape before
  implementing the delegation methods.
- No existing `save_config`/config-write-back helper was confirmed to
  exist; the builder must check `tony/core/config/reload.py` and
  `watcher.py` first and only add one if genuinely missing (YAGNI).
