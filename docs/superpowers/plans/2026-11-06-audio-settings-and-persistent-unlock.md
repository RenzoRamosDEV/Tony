# Audio Device Settings + Persistent Edith Unlock Implementation Plan

> **For agentic workers:** Implement task-by-task, TDD (red/green/commit) per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick input/output audio devices from a settings overlay, live-switchable and persisted, and make Edith's unlock state survive an app restart within the existing idle window.

**Architecture:** Two independent vertical slices sharing the same `Command`/`CoreEvent` bridge convention. Audio: `VoiceSettings` gains two fields; `sounddevice_io.py` resolves a device *name* to an index lazily on each use; a new bridge command pair (`list_devices`, `set_audio_device`) and event (`audio_devices`) carry the UI round-trip; a new `AudioSettingsOverlay.tsx` mirrors `PinOverlay.tsx`'s modal pattern. Unlock: a new `UnlockExpiry` file-backed timestamp, read by `EdithSession` at construction and refreshed/cleared exactly where `touch()`/relock logic already runs today.

**Tech Stack:** Python 3.12, pydantic, `sounddevice`, pytest; React/TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-06-audio-settings-and-persistent-unlock-design.md`

## Global Constraints

- `VoiceSettings` is `extra="forbid"`; add fields there deliberately, no stray config keys elsewhere.
- Devices are identified and persisted **by name**, never by numeric index.
- `Command`/`CoreEvent` are closed discriminated unions on both sides (Python `TypeAdapter` in `commands.py`, TS union in `bridge/types.ts`) — extend both in lockstep.
- `config/edith.lock` (PIN hash) and the new `config/edith.session` file must stay out of git (`.gitignore`), and the PIN value itself is never persisted anywhere, before or after this change.
- Device resolution (`sounddevice.query_devices()`) happens lazily at `open()`/`play()` time, never eagerly at startup.
- A persisted device name that's no longer present falls back to system default for that call without clearing the saved preference (auto-recovers if replugged).
- `AudioSettingsOverlay` follows the `PinOverlay` modal pattern (gear-icon trigger, `role="dialog" aria-modal="true"`) — never a permanently docked panel.
- Every `EdithSession` transition to `locked` clears `UnlockExpiry`; only a successful `attempt()` (and `touch()` while still unlocked) refreshes it; back-off/wrong-PIN failures never touch it (session was never unlocked in that sequence).

## Review Focus

- Switching the input device while a listening session is active must close and reopen the stream on the new device, not silently keep using the old one.
- A device name no longer in `sounddevice.query_devices()` must fall back to system default and surface a warning, not raise/crash the open()/play() call.
- `EdithSession` restart-unlock must only happen when the PIN lock file is still valid **and** `pin_required` is true **and** the expiry hasn't passed — not on expiry alone (e.g. the user ran `tony pin set` again, invalidating any stale expiry's assumptions is out of scope, but a missing/invalid lock file must still force `locked`).
- `UnlockExpiry.is_valid()` must treat a missing file, a corrupt/unparseable file, and an expired timestamp all as "not valid" (no exceptions escaping to the caller).
- `set_audio_device` with `device: null` must select system default, not be rejected as an invalid value, and must be distinguishable from "no selection yet".

---

### Task 1: `VoiceSettings` fields + config write-back

**Files:**
- Modify: `tony/core/config/settings.py`
- Test: `tests/core/config/test_settings.py`

**Interfaces:**
- Produces: `VoiceSettings.input_device: str | None = None`, `VoiceSettings.output_device: str | None = None`; `save_config(root: Path, config: TonyConfig) -> None` (writes `config/tony.yaml` via `yaml.safe_dump(config.model_dump(), ...)`, same directory-creation behavior as `PinStore.set`'s atomic temp-file-then-`os.replace` pattern — reuse that pattern here too, to avoid partial writes).

- [ ] **Step 1: Write the failing tests**

```python
def test_voice_settings_defaults_to_system_default_devices():
    assert VoiceSettings().input_device is None
    assert VoiceSettings().output_device is None

def test_save_config_round_trips_through_load_config(tmp_path):
    config = TonyConfig(voice=VoiceSettings(input_device="USB Mic"))
    save_config(tmp_path, config)
    assert load_config(tmp_path).voice.input_device == "USB Mic"

def test_save_config_writes_atomically_no_temp_file_left(tmp_path):
    save_config(tmp_path, TonyConfig())
    assert sorted(p.name for p in (tmp_path / "config").iterdir()) == ["tony.yaml"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/config/test_settings.py -v`
Expected: FAIL (`input_device`/`save_config` not defined)

- [ ] **Step 3: Implement the fields and `save_config`**

Add the two fields to `VoiceSettings` with their defaults. Implement `save_config` using `tempfile.mkstemp(dir=path.parent, prefix=".tony.yaml.")` + `os.fdopen` + `yaml.safe_dump` + `os.replace`, mirroring `PinStore.set`'s try/except cleanup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/config/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/config/settings.py tests/core/config/test_settings.py
git commit -m "feat(config): add audio device fields and config write-back"
```

---

### Task 2: `devices.py` — device enumeration

**Files:**
- Create: `tony/core/voice/devices.py`
- Test: `tests/core/voice/test_devices.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class DeviceInfo: name: str; kind: Literal["input", "output"]; is_default: bool` and `list_devices(*, query: Callable[[], Any] = _default_query) -> tuple[DeviceInfo, ...]`, where `query` defaults to calling `sounddevice.query_devices()` (import `sounddevice` lazily inside the function, same lazy-import convention as `sounddevice_io.py`). A device with `max_input_channels > 0` yields an input `DeviceInfo`; `max_output_channels > 0` yields an output one (one device can yield both). `is_default` compares against `sounddevice.default.device` (a `[input_index, output_index]` pair) for the matching kind.

- [ ] **Step 1: Write the failing tests**

```python
FAKE_DEVICES = [
    {"name": "Built-in Mic", "max_input_channels": 2, "max_output_channels": 0},
    {"name": "USB Headset", "max_input_channels": 1, "max_output_channels": 2},
    {"name": "HDMI Out", "max_input_channels": 0, "max_output_channels": 2},
]

def test_list_devices_splits_by_channel_kind():
    devices = list_devices(query=lambda: (FAKE_DEVICES, [0, 2]))
    names = {(d.name, d.kind) for d in devices}
    assert names == {
        ("Built-in Mic", "input"), ("USB Headset", "input"),
        ("USB Headset", "output"), ("HDMI Out", "output"),
    }

def test_list_devices_marks_the_default_per_kind():
    devices = list_devices(query=lambda: (FAKE_DEVICES, [0, 2]))
    assert next(d for d in devices if d.name == "Built-in Mic").is_default
    assert next(d for d in devices if d.name == "HDMI Out" and d.kind == "output").is_default
    assert not next(d for d in devices if d.name == "USB Headset" and d.kind == "input").is_default
```

Note: `query` here returns `(devices_list, default_pair)` for testability — real `sounddevice.query_devices()` returns the device list and `sounddevice.default.device` is read separately; the implementation's `_default_query` wraps both into that same tuple shape so the test double is a drop-in replacement.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/voice/test_devices.py -v`
Expected: FAIL (`devices.py` not found)

- [ ] **Step 3: Implement `DeviceInfo` and `list_devices`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/voice/test_devices.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/voice/devices.py tests/core/voice/test_devices.py
git commit -m "feat(voice): add audio device enumeration"
```

---

### Task 3: `sounddevice_io.py` — device-aware input/output + `ports.py` protocol

**Files:**
- Modify: `tony/core/voice/engines/sounddevice_io.py`
- Modify: `tony/core/voice/ports.py`
- Test: `tests/voice/test_sounddevice_io.py` (new — the real-hardware tests already in `tests/voice/test_engines.py` stay as-is; this new file tests the device-selection logic against a fake `sounddevice` module, no real hardware needed)

**Interfaces:**
- Consumes: nothing new.
- Produces: `SoundDeviceInput.__init__(self, device: str | None = None)`; `SoundDeviceInput.set_device(self, device: str | None) -> None`; `SoundDeviceOutput.__init__(self, device: str | None = None)`; `SoundDeviceOutput.set_device(self, device: str | None) -> None`; module-level `_resolve_device(name: str | None, kind: Literal["input", "output"]) -> int | None` (returns `None` for default or not-found, else the device's index per `sounddevice.query_devices()` order); `ports.AudioInput`/`AudioOutput` Protocols gain `set_device(self, device: str | None) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
class FakeStream:
    def __init__(self, **kwargs): self.kwargs = kwargs; self.started = False; self.stopped = False
    def start(self): self.started = True
    def stop(self): self.stopped = True
    def close(self): pass

class FakeSoundDevice:
    def __init__(self, devices):
        self._devices = devices
        self.streams = []
    def query_devices(self):
        return self._devices
    def RawInputStream(self, **kwargs):
        stream = FakeStream(**kwargs)
        self.streams.append(stream)
        return stream

DEVICES = [{"name": "Mic A"}, {"name": "Mic B"}]

def test_resolve_device_finds_index_by_name(monkeypatch):
    fake = FakeSoundDevice(DEVICES)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert _resolve_device("Mic B", "input") == 1

def test_resolve_device_falls_back_to_default_when_missing(monkeypatch):
    fake = FakeSoundDevice(DEVICES)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert _resolve_device("Mic Z", "input") is None

def test_set_device_reopens_an_open_stream_on_the_new_device(monkeypatch):
    fake = FakeSoundDevice(DEVICES)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    audio = SoundDeviceInput("Mic A")
    audio.open(lambda frame: None)
    audio.set_device("Mic B")
    assert fake.streams[0].stopped
    assert fake.streams[-1].kwargs["device"] == 1

def test_set_device_is_a_no_op_on_stream_state_when_nothing_is_open(monkeypatch):
    fake = FakeSoundDevice(DEVICES)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    audio = SoundDeviceInput("Mic A")
    audio.set_device("Mic B")  # must not raise
    assert fake.streams == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/voice/test_sounddevice_io.py -v`
Expected: FAIL (constructor/`set_device`/`_resolve_device` not defined)

- [ ] **Step 3: Implement device-aware `SoundDeviceInput`/`SoundDeviceOutput` and `_resolve_device`**

`open()` resolves the device at call time and stores the `on_frame` callback on `self` so `set_device` can reopen with it. `SoundDeviceOutput.play()` resolves at call time and passes `device=index` to `sounddevice.play(...)`; `set_device` on output just updates the stored name.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/voice/test_sounddevice_io.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/voice/engines/sounddevice_io.py tony/core/voice/ports.py tests/voice/test_sounddevice_io.py
git commit -m "feat(voice): select and live-switch audio devices by name"
```

---

### Task 4: `loader.py` — wire settings into engine construction

**Files:**
- Modify: `tony/core/voice/engines/loader.py`
- Modify: `tests/core/voice/test_loader.py`

**Interfaces:**
- Consumes: `SoundDeviceInput(device=...)`, `SoundDeviceOutput(device=...)` (Task 3).
- Produces: `build_engines` now passes `settings.input_device` / `settings.output_device` through.

- [ ] **Step 1: Write the failing test**

```python
def test_build_engines_passes_device_settings_through(monkeypatch):
    captured = {}
    class SpyInput:
        def __init__(self, device=None): captured["input"] = device
    class SpyOutput:
        def __init__(self, device=None): captured["output"] = device
    monkeypatch.setattr("tony.core.voice.engines.sounddevice_io.SoundDeviceInput", SpyInput)
    monkeypatch.setattr("tony.core.voice.engines.sounddevice_io.SoundDeviceOutput", SpyOutput)
    build_engines(VoiceSettings(input_device="Mic A", output_device="Speak B"), ("kokoro/em_alex",))
    assert captured == {"input": "Mic A", "output": "Speak B"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/voice/test_loader.py -v`
Expected: FAIL

- [ ] **Step 3: Pass `settings.input_device`/`settings.output_device` into the constructors in `build_engines`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/voice/test_loader.py -v`
Expected: PASS (including pre-existing tests in this file)

- [ ] **Step 5: Commit**

```bash
git add tony/core/voice/engines/loader.py tests/core/voice/test_loader.py
git commit -m "feat(voice): build engines with configured audio devices"
```

---

### Task 5: `Listener`/`Speaker` — delegate device switch

**Files:**
- Modify: `tony/core/voice/listener.py`
- Modify: `tony/core/voice/speaker.py`
- Modify: `tests/core/voice/test_listener.py`, `tests/core/voice/test_speaker.py`

**Interfaces:**
- Consumes: `AudioInput.set_device`/`AudioOutput.set_device` (Task 3).
- Produces: `Listener.set_device(self, device: str | None) -> None` → `self._audio.set_device(device)`; `Speaker.set_device(self, device: str | None) -> None` → `self._output.set_device(device)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_listener_set_device_delegates_to_audio():
    audio = FakeAudioInput()  # existing fake in tests/fakes/voice.py — check it has/gets a set_device spy
    listener = Listener(audio, FakeVad(), FakeStt(), report=lambda *_: None)
    listener.set_device("Mic B")
    assert audio.device == "Mic B"

def test_speaker_set_device_delegates_to_output():
    output = FakeAudioOutput()
    speaker = Speaker(FakeTts(), output, report=lambda *_: None)
    speaker.set_device("Speak B")
    assert output.device == "Speak B"
```

Check `tests/fakes/voice.py` first — add a `set_device`/`device` attribute to the existing fakes there if they don't already support it, rather than creating new fakes.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/voice/test_listener.py tests/core/voice/test_speaker.py -v`
Expected: FAIL

- [ ] **Step 3: Add `set_device` to `Listener` and `Speaker`, and to the fakes in `tests/fakes/voice.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/voice/test_listener.py tests/core/voice/test_speaker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/voice/listener.py tony/core/voice/speaker.py tests/fakes/voice.py tests/core/voice/test_listener.py tests/core/voice/test_speaker.py
git commit -m "feat(voice): let Listener and Speaker switch audio device"
```

---

### Task 6: `VoiceService` — public device-switch API

**Files:**
- Modify: `tony/core/voice/service.py`
- Modify: `tests/core/voice/test_service.py`

**Interfaces:**
- Consumes: `Listener.set_device`, `Speaker.set_device` (Task 5).
- Produces: `VoiceService.set_input_device(self, device: str | None) -> None`, `VoiceService.set_output_device(self, device: str | None) -> None` — no-op (do not raise) when the engines haven't loaded yet (`self._listener`/`self._speaker` are `None`); the selection still reaches the engines on the next full load via the already-persisted config (Task 4), since live switching only covers an already-open stream per the design's stated scope.

- [ ] **Step 1: Write the failing tests**

```python
def test_set_input_device_delegates_once_loaded(service_with_loaded_engines):
    service, listener, _ = service_with_loaded_engines
    service.set_input_device("Mic B")
    assert listener.device == "Mic B"

def test_set_output_device_is_a_no_op_before_engines_load():
    service = VoiceService(loader=lambda *a: Unavailable("loading"))
    service.set_output_device("Speak B")  # must not raise
```

Use the existing `service_harness.py` fixtures in `tests/core/voice/` for `service_with_loaded_engines`-equivalent setup — check that file's existing pattern (used by `test_service_levels.py`/`test_service_confirmation.py`) before adding a new fixture.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/voice/test_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `set_input_device`/`set_output_device` on `VoiceService`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/voice/test_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/voice/service.py tests/core/voice/test_service.py
git commit -m "feat(voice): expose live audio device switching on VoiceService"
```

---

### Task 7: `commands.py` — `ListDevices` / `SetAudioDevice`

**Files:**
- Modify: `tony/core/orchestrator/commands.py`
- Modify: `tests/core/orchestrator/test_commands.py` (or wherever `parse_command` is tested today — locate it first; if no dedicated file exists, add `tests/core/orchestrator/test_commands.py`)

**Interfaces:**
- Produces:
  ```python
  class ListDevices(_Command):
      type: Literal["list_devices"] = "list_devices"

  class SetAudioDevice(_Command):
      type: Literal["set_audio_device"] = "set_audio_device"
      kind: Literal["input", "output"]
      device: str | None
  ```
  Both added to the `Command` discriminated union.

- [ ] **Step 1: Write the failing tests**

```python
def test_parses_list_devices():
    assert parse_command({"type": "list_devices"}) == ListDevices()

def test_parses_set_audio_device():
    cmd = parse_command({"type": "set_audio_device", "kind": "input", "device": "Mic A"})
    assert cmd == SetAudioDevice(kind="input", device="Mic A")

def test_parses_set_audio_device_with_null_device_as_system_default():
    cmd = parse_command({"type": "set_audio_device", "kind": "output", "device": None})
    assert cmd.device is None

def test_rejects_set_audio_device_with_bad_kind():
    with pytest.raises(InvalidCommand):
        parse_command({"type": "set_audio_device", "kind": "sideways", "device": None})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/orchestrator/test_commands.py -v` (adjust path once located)
Expected: FAIL

- [ ] **Step 3: Add `ListDevices` and `SetAudioDevice` to `commands.py`, included in the `Command` union**

- [ ] **Step 4: Run tests to verify they pass**

Run: same as step 2
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/orchestrator/commands.py tests/core/orchestrator/test_commands.py
git commit -m "feat(orchestrator): add list_devices and set_audio_device commands"
```

---

### Task 8: `core_events.py` — `audio_devices` event

**Files:**
- Modify: `tony/core/events/core_events.py`
- Test: `tests/core/events/test_core_events.py` (locate the existing event-builder test file first and add alongside; if none exists, create it following the file's own docstring/`_event` pattern)

**Interfaces:**
- Produces:
  ```python
  def audio_devices(
      input: tuple[DeviceInfo, ...],
      output: tuple[DeviceInfo, ...],
      *,
      selected_input: str | None,
      selected_output: str | None,
      input_fallback_warning: str | None = None,
      output_fallback_warning: str | None = None,
      clock: Clock = utc_now,
  ) -> Event
  ```
  serialized the same way `mcp_status`/`auth` are (list-of-`DeviceInfo` fields become list-of-dicts — call `.__dict__`/`dataclasses.asdict` per item, since `Event` is a plain `dict`).

- [ ] **Step 1: Write the failing test**

```python
def test_audio_devices_event_shape():
    event = audio_devices(
        (DeviceInfo(name="Mic A", kind="input", is_default=True),), (),
        selected_input="Mic A", selected_output=None,
    )
    assert event["type"] == "audio_devices"
    assert event["input"] == [{"name": "Mic A", "kind": "input", "is_default": True}]
    assert event["selected_input"] == "Mic A"
    assert event["input_fallback_warning"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/events/test_core_events.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `audio_devices` in `core_events.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/events/test_core_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/events/core_events.py tests/core/events/test_core_events.py
git commit -m "feat(events): add audio_devices event"
```

---

### Task 9: `runtime.py` — dispatch `ListDevices`/`SetAudioDevice`

**Files:**
- Modify: `tony/core/orchestrator/runtime.py`
- Modify: `tests/core/orchestrator/test_runtime_voice.py` (existing voice-related runtime test file — add cases here; create a sibling if device dispatch doesn't fit its fixtures)

**Interfaces:**
- Consumes: `tony.core.voice.devices.list_devices` (Task 2), `VoiceService.set_input_device`/`set_output_device` (Task 6), `core_events.audio_devices` (Task 8), `save_config` (Task 1), `ListDevices`/`SetAudioDevice` (Task 7).
- Produces: `CoreRuntime._dispatch` handles both commands:
  - `ListDevices` → `self._publish(core_events.audio_devices(*split_by_kind(list_devices()), selected_input=self._config.voice.input_device, selected_output=self._config.voice.output_device))` (store `self._config = config` in `_start()` if not already held — check first).
  - `SetAudioDevice` → call `self.voice.set_input_device(device)` or `set_output_device(device)` per `kind` (no-op/log if `self.voice is None`), update the in-memory config's `VoiceSettings` field, call `save_config(self._root, self._config)`, then publish a fresh `audio_devices` event reflecting the new selection.

- [ ] **Step 1: Write the failing tests**

```python
async def test_list_devices_publishes_audio_devices_event(runtime_harness):
    runtime, published = runtime_harness
    runtime._dispatch(ListDevices())
    assert published[-1]["type"] == "audio_devices"

async def test_set_audio_device_applies_persists_and_republishes(runtime_harness, tmp_path):
    runtime, published = runtime_harness
    runtime._dispatch(SetAudioDevice(kind="input", device="Mic A"))
    assert runtime.voice.set_input_device_calls == ["Mic A"]  # fake VoiceService records calls
    assert load_config(tmp_path).voice.input_device == "Mic A"
    assert published[-1]["type"] == "audio_devices"
    assert published[-1]["selected_input"] == "Mic A"
```

Build `runtime_harness` by following the existing fixture pattern already used in `tests/core/orchestrator/test_runtime_voice.py` for constructing a `CoreRuntime` with a fake `VoiceService` — reuse it, don't invent a parallel one.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/orchestrator/test_runtime_voice.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the two new branches in `CoreRuntime._dispatch`, importing `list_devices`/`save_config`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/orchestrator/test_runtime_voice.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/orchestrator/runtime.py tests/core/orchestrator/test_runtime_voice.py
git commit -m "feat(orchestrator): wire audio device commands into the core runtime"
```

---

### Task 10: `unlock_expiry.py` — persisted "unlocked until"

**Files:**
- Create: `tony/core/guard/unlock_expiry.py`
- Test: `tests/core/guard/test_unlock_expiry.py`

**Interfaces:**
- Produces:
  ```python
  class UnlockExpiry:
      def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None: ...
      def is_valid(self) -> bool: ...
      def refresh(self, lock_after_min: int) -> None: ...
      def clear(self) -> None: ...
  ```
  File path `root / "config/edith.session"`. `refresh` writes `now + lock_after_min * 60` as a float, atomically (same temp-file + `os.replace` pattern as `PinStore.set`). `is_valid` returns `False` for a missing file, an unparseable file, and an expired timestamp — never raises. `clear` deletes the file, no-op if absent.

- [ ] **Step 1: Write the failing tests**

```python
def test_missing_file_is_not_valid(tmp_path):
    assert not UnlockExpiry(tmp_path).is_valid()

def test_refresh_then_is_valid_before_expiry(tmp_path):
    clock = Clock(start=1000.0)
    expiry = UnlockExpiry(tmp_path, clock=clock)
    expiry.refresh(lock_after_min=30)
    clock.now += 60
    assert expiry.is_valid()

def test_is_valid_false_after_expiry(tmp_path):
    clock = Clock(start=1000.0)
    expiry = UnlockExpiry(tmp_path, clock=clock)
    expiry.refresh(lock_after_min=30)
    clock.now += 30 * 60 + 1
    assert not expiry.is_valid()

@pytest.mark.parametrize("content", ["", "not a number", "{}"])
def test_corrupt_file_is_not_valid(tmp_path, content):
    path = tmp_path / "config" / "edith.session"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    assert not UnlockExpiry(tmp_path).is_valid()

def test_clear_removes_the_file_and_is_idempotent(tmp_path):
    expiry = UnlockExpiry(tmp_path)
    expiry.refresh(lock_after_min=30)
    expiry.clear()
    assert not (tmp_path / "config" / "edith.session").exists()
    expiry.clear()  # no error

def test_refresh_writes_atomically_no_temp_file_left(tmp_path):
    expiry = UnlockExpiry(tmp_path)
    expiry.refresh(lock_after_min=30)
    assert sorted(p.name for p in (tmp_path / "config").iterdir() if "session" in p.name) == ["edith.session"]
```

(`Clock` is a tiny test double with a mutable `.now` and `__call__`, same shape as `tests/core/guard/test_session.py`'s `Clock`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/guard/test_unlock_expiry.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `UnlockExpiry`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/guard/test_unlock_expiry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/guard/unlock_expiry.py tests/core/guard/test_unlock_expiry.py
git commit -m "feat(guard): add persisted unlock-expiry store"
```

---

### Task 11: `EdithSession` — restart-unlock from `UnlockExpiry`

**Files:**
- Modify: `tony/core/guard/session.py`
- Modify: `tests/core/guard/test_session.py`

**Interfaces:**
- Consumes: `UnlockExpiry` (Task 10): `.is_valid()`, `.refresh(lock_after_min)`, `.clear()`.
- Produces: `EdithSession.__init__(self, auth, pins, *, monotonic=time.monotonic, expiry: UnlockExpiry | None = None)`. New constructor branch: when `expiry is not None and auth.pin_required and pins.has_valid_lock() and expiry.is_valid()`, set `self.status = AuthStatus("unlocked", "unlocked", 0)` and `self._last_message = self._monotonic()` (checked *before* the existing `not auth.pin_required` / `not pins.has_valid_lock()` branches, since those still take priority when they apply). `attempt()` success and `touch()`'s non-relocking path call `self._expiry.refresh(self._auth.lock_after_min)` when `self._expiry is not None`. Every place `self.status` becomes `locked` (`touch()` idle relock, `cancel()`, `_lock_conversation_only` for any reason) calls `self._expiry.clear()` when `self._expiry is not None`. Back-off/wrong-PIN failures in `attempt()` do not touch `self._expiry`.

- [ ] **Step 1: Write the failing tests**

```python
class FakeExpiry:
    def __init__(self, valid=False):
        self.valid = valid
        self.refreshed_with: list[int] = []
        self.cleared = False
    def is_valid(self): return self.valid
    def refresh(self, lock_after_min): self.refreshed_with.append(lock_after_min)
    def clear(self): self.cleared = True

def test_restart_unlocked_when_expiry_valid_and_lock_valid():
    clock, pins, expiry = Clock(), FakePins(valid_lock=True), FakeExpiry(valid=True)
    edith = EdithSession(Auth(pin_required=True), pins, monotonic=clock, expiry=expiry)
    assert edith.unlocked

def test_restart_stays_locked_when_expiry_invalid():
    clock, pins, expiry = Clock(), FakePins(valid_lock=True), FakeExpiry(valid=False)
    edith = EdithSession(Auth(pin_required=True), pins, monotonic=clock, expiry=expiry)
    assert not edith.unlocked

def test_restart_stays_locked_when_lock_file_invalid_even_if_expiry_valid():
    clock, pins, expiry = Clock(), FakePins(valid_lock=False), FakeExpiry(valid=True)
    edith = EdithSession(Auth(pin_required=True), pins, monotonic=clock, expiry=expiry)
    assert not edith.unlocked

def test_successful_attempt_refreshes_expiry():
    clock, pins, expiry = Clock(), FakePins(valid_lock=True), FakeExpiry()
    edith = EdithSession(Auth(pin_required=True, lock_after_min=30), pins, monotonic=clock, expiry=expiry)
    edith.attempt(PIN)
    assert expiry.refreshed_with == [30]

def test_failed_attempt_does_not_touch_expiry():
    clock, pins, expiry = Clock(), FakePins(valid_lock=True), FakeExpiry()
    edith = EdithSession(Auth(pin_required=True), pins, monotonic=clock, expiry=expiry)
    edith.attempt("0000")
    assert expiry.refreshed_with == [] and not expiry.cleared

def test_idle_relock_clears_expiry():
    clock, pins, expiry = Clock(), FakePins(valid_lock=True), FakeExpiry()
    edith = EdithSession(Auth(pin_required=True, lock_after_min=1), pins, monotonic=clock, expiry=expiry)
    edith.attempt(PIN)
    edith.touch()
    clock.now += 61
    edith.touch()
    assert expiry.cleared

def test_cancel_clears_expiry():
    clock, pins, expiry = Clock(), FakePins(valid_lock=True), FakeExpiry()
    edith = EdithSession(Auth(pin_required=True), pins, monotonic=clock, expiry=expiry)
    edith.cancel()
    assert expiry.cleared
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/guard/test_session.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the `expiry` parameter, restart-unlock branch, and refresh/clear call sites in `EdithSession`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/guard/test_session.py -v`
Expected: PASS (including all pre-existing tests in this file)

- [ ] **Step 5: Commit**

```bash
git add tony/core/guard/session.py tests/core/guard/test_session.py
git commit -m "feat(guard): persist Edith's unlock state across restarts"
```

---

### Task 12: Wire `UnlockExpiry` into `CoreRuntime` + `.gitignore`

**Files:**
- Modify: `tony/core/orchestrator/runtime.py`
- Modify: `.gitignore`
- Modify: `tests/core/orchestrator/test_runtime_voice.py` (or the file covering `_start`/session construction — locate it)

**Interfaces:**
- Consumes: `UnlockExpiry` (Task 10).
- Produces: `CoreRuntime._start()`'s `EdithSession(...)` construction gains `expiry=UnlockExpiry(self._root)`.

- [ ] **Step 1: Write the failing test**

```python
async def test_start_constructs_session_with_unlock_expiry(tmp_path, ...):
    # whatever harness the existing _start tests use; assert runtime.session restart-unlocks
    # when a prior UnlockExpiry().refresh(...) was written before constructing the runtime.
    UnlockExpiry(tmp_path).refresh(lock_after_min=30)
    PinStore(tmp_path).set("4821")
    runtime = build_runtime(tmp_path)  # existing harness helper
    await runtime._start_for_test()  # or whatever the existing tests call
    assert runtime.session.unlocked
```

Adapt exactly to whatever harness/helper the existing runtime-startup tests already use — do not invent a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/orchestrator/test_runtime_voice.py -v`
Expected: FAIL

- [ ] **Step 3: Pass `expiry=UnlockExpiry(self._root)` into the `EdithSession(...)` call in `_start()`; add `config/edith.session` to `.gitignore` next to `config/edith.lock`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/orchestrator/test_runtime_voice.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/core/orchestrator/runtime.py .gitignore tests/core/orchestrator/test_runtime_voice.py
git commit -m "feat(orchestrator): persist Edith's unlock across app restarts"
```

---

### Task 13: Bridge types — `Command`/`CoreEvent` additions (TypeScript)

**Files:**
- Modify: `tony/apps/desktop/web/src/bridge/types.ts`

**Interfaces:**
- Produces, in `Command`: `| { type: "list_devices" } | { type: "set_audio_device"; kind: "input" | "output"; device: string | null }`. New interface:
  ```ts
  export interface AudioDeviceOption { name: string; is_default: boolean }
  export interface AudioDevicesEvent extends Base {
    type: "audio_devices";
    input: AudioDeviceOption[];
    output: AudioDeviceOption[];
    selected_input: string | null;
    selected_output: string | null;
    input_fallback_warning: string | null;
    output_fallback_warning: string | null;
  }
  ```
  added to the `CoreEvent` union.

- [ ] **Step 1: Add the types and union members described above**

- [ ] **Step 2: Type-check**

Run: `npm --prefix tony/apps/desktop/web run lint`
Expected: no new errors (this file alone has no runtime behavior to unit-test; the type-check is the verification step)

- [ ] **Step 3: Commit**

```bash
git add tony/apps/desktop/web/src/bridge/types.ts
git commit -m "feat(bridge): add audio device Command/CoreEvent types"
```

---

### Task 14: `state/reducer.ts` — audio-devices state slice

**Files:**
- Modify: `tony/apps/desktop/web/src/state/reducer.ts`
- Test: `tony/apps/desktop/web/src/state/reducer.test.ts` (locate the existing reducer test file — it likely already exists given `App.test.tsx`/component tests follow this convention; add cases there)

**Interfaces:**
- Consumes: `AudioDevicesEvent` (Task 13).
- Produces:
  ```ts
  export interface AudioDevicesView {
    input: AudioDeviceOption[];
    output: AudioDeviceOption[];
    selectedInput: string | null;
    selectedOutput: string | null;
    inputWarning: string | null;
    outputWarning: string | null;
  }
  ```
  added as `UiState.audioDevices`, defaulted in `initialState()` to `{ input: [], output: [], selectedInput: null, selectedOutput: null, inputWarning: null, outputWarning: null }`; a new `case "audio_devices":` in the `onEvent` switch maps the event 1:1 onto this shape (camelCase renames only).

- [ ] **Step 1: Write the failing test**

```ts
test("audio_devices event updates the audioDevices slice", () => {
  const state = reduce(initialState(), {
    kind: "event",
    now: Date.now(),
    event: {
      type: "audio_devices", ts: "",
      input: [{ name: "Mic A", is_default: true }], output: [],
      selected_input: "Mic A", selected_output: null,
      input_fallback_warning: null, output_fallback_warning: null,
    },
  });
  expect(state.audioDevices.selectedInput).toBe("Mic A");
  expect(state.audioDevices.input).toEqual([{ name: "Mic A", is_default: true }]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix tony/apps/desktop/web run test`
Expected: FAIL

- [ ] **Step 3: Add the `audioDevices` field, default, and `"audio_devices"` case**

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm --prefix tony/apps/desktop/web run test`
Expected: PASS (including all pre-existing reducer tests)

- [ ] **Step 5: Commit**

```bash
git add tony/apps/desktop/web/src/state/reducer.ts tony/apps/desktop/web/src/state/reducer.test.ts
git commit -m "feat(web): track audio device state in the reducer"
```

---

### Task 15: `AudioSettingsOverlay.tsx`

**Files:**
- Create: `tony/apps/desktop/web/src/components/AudioSettingsOverlay.tsx`
- Test: `tony/apps/desktop/web/src/components/AudioSettingsOverlay.test.tsx`

**Interfaces:**
- Consumes: `AudioDevicesView` (Task 14), `Command` (Task 13).
- Produces:
  ```ts
  interface Props {
    devices: AudioDevicesView;
    onCommand: (command: Command) => void;
  }
  export function AudioSettingsOverlay({ devices, onCommand }: Props): JSX.Element
  ```
  Internal open/closed state (`useState`), mirroring `PinOverlay`'s hidden/shown split: closed renders a gear-icon trigger button (`className="settings-trigger holo-frame holo"`, following `PinOverlay`'s `unlock-control` button styling convention) that, on click, both opens the overlay and sends `{ type: "list_devices" }`; open renders `role="dialog" aria-modal="true"` with two `<select>` elements (input/output), each option built from `devices.input`/`devices.output` plus a leading `"Sistema (predeterminado)"` option mapped to `null`, `value={devices.selectedInput ?? ""}` / `selectedOutput`, `onChange` dispatching `{ type: "set_audio_device", kind: "input"|"output", device: e.target.value || null }`; a close button; inline warning text under each `<select>` when `devices.inputWarning`/`outputWarning` is non-null.

- [ ] **Step 1: Write the failing tests**

```tsx
test("clicking the gear trigger opens the overlay and requests the device list", () => {
  const onCommand = vi.fn();
  render(<AudioSettingsOverlay devices={emptyDevices} onCommand={onCommand} />);
  fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
  expect(onCommand).toHaveBeenCalledWith({ type: "list_devices" });
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

test("selecting an input device sends set_audio_device", () => {
  const onCommand = vi.fn();
  const devices = { ...emptyDevices, input: [{ name: "Mic A", is_default: true }] };
  render(<AudioSettingsOverlay devices={devices} onCommand={onCommand} />);
  fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
  fireEvent.change(screen.getByLabelText(/micrófono/i), { target: { value: "Mic A" } });
  expect(onCommand).toHaveBeenCalledWith({ type: "set_audio_device", kind: "input", device: "Mic A" });
});

test("choosing system default sends a null device", () => {
  const onCommand = vi.fn();
  render(<AudioSettingsOverlay devices={emptyDevices} onCommand={onCommand} />);
  fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
  fireEvent.change(screen.getByLabelText(/micrófono/i), { target: { value: "" } });
  expect(onCommand).toHaveBeenCalledWith({ type: "set_audio_device", kind: "input", device: null });
});

test("shows the input fallback warning when present", () => {
  const devices = { ...emptyDevices, inputWarning: "Dispositivo 'X' no disponible; usando predeterminado." };
  render(<AudioSettingsOverlay devices={devices} onCommand={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
  expect(screen.getByText(/no disponible/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix tony/apps/desktop/web run test`
Expected: FAIL (component not found)

- [ ] **Step 3: Implement `AudioSettingsOverlay`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm --prefix tony/apps/desktop/web run test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tony/apps/desktop/web/src/components/AudioSettingsOverlay.tsx tony/apps/desktop/web/src/components/AudioSettingsOverlay.test.tsx
git commit -m "feat(web): add audio settings overlay"
```

---

### Task 16: Wire `AudioSettingsOverlay` into `App.tsx`

**Files:**
- Modify: `tony/apps/desktop/web/src/App.tsx`
- Modify: `tony/apps/desktop/web/src/App.test.tsx`

**Interfaces:**
- Consumes: `AudioSettingsOverlay` (Task 15), `state.audioDevices` (Task 14).

- [ ] **Step 1: Write the failing test**

```tsx
test("renders the audio settings trigger and forwards commands through the bridge", async () => {
  const sent: Command[] = [];
  const bridge = fakeBridge({ onSend: (c) => sent.push(c) });
  render(<App connect={() => Promise.resolve(bridge)} />);
  fireEvent.click(await screen.findByRole("button", { name: /ajustes de audio/i }));
  expect(sent).toContainEqual({ type: "list_devices" });
});
```

Follow `App.test.tsx`'s existing `fakeBridge`/`connect` helper conventions exactly — do not introduce a parallel bridge double.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix tony/apps/desktop/web run test`
Expected: FAIL

- [ ] **Step 3: Render `<AudioSettingsOverlay devices={state.audioDevices} onCommand={send} />` in `App.tsx`, alongside `PinOverlay`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm --prefix tony/apps/desktop/web run test`
Expected: PASS (full suite)

- [ ] **Step 5: Run the full verification pass**

Run: `npm --prefix tony/apps/desktop/web run lint && npm --prefix tony/apps/desktop/web run test && npm --prefix tony/apps/desktop/web run build && uv run pytest`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add tony/apps/desktop/web/src/App.tsx tony/apps/desktop/web/src/App.test.tsx
git commit -m "feat(web): wire the audio settings overlay into the app shell"
```
