# Design

## Context

- `CoreRuntime` (Qt-free) owns one asyncio loop in the `tony-core` thread, parses JSON commands, runs one front-agent turn at a time (`Conversation.handle`) and publishes events through `MaskingPublisher` into `QtEventBridge`. The desktop is presenters (pure, mutated) plus widgets and `app.py` (Qt glue, excluded from mutation).
- `ConfirmationBroker` is the desktop confirmation channel: `needs_confirmation` out, `confirm` command in; Edith wraps `ask` in `asyncio.wait_for(confirm_timeout_s)` and records `timeout`. A stale `confirm` is ignored.
- `Conversation` already resolves the per-message mode (`/v`, `/t` prefix or persisted) and publishes `result` turn with it; `token` events are always streamed.
- `tony/core/voice/` exists as an empty package; `voice` pytest marker exists and is excluded by `addopts`.
- `voice.tts` is validated only as `^kokoro/\S+$`; bundled Viernes uses `em_alex`, Edith `ef_dora`.
- v1 (branch `main`) proved the engine calls: faster-whisper `WhisperModel(size, device="cpu", compute_type="int8")` with `beam_size=1, vad_filter=False, condition_on_previous_text=False`; `silero_vad.load_silero_vad()` over 512-sample windows; Kokoro `KPipeline(lang_code="e", repo_id="hexgrad/Kokoro-82M")` with `load_voice` tensors combined arithmetically. v1 measured voice round trip p50 ~9.4 s on this CPU.

## Goals / Non-Goals

**Goals:**
- Voice as an add-on around the existing core: no change to the guard, broker, runner or Conversation's model call.
- All voice and desktop logic testable offline with fakes; real engines and OS services only in thin adapters.
- One path for confirmation answers (the `confirm` command) whether they come from the banner or the voice.

**Non-Goals:**
- Wake word, barge-in (the mic is closed while Tony speaks), streaming partial transcripts, echo cancellation.
- Voice in `tony chat` / `tony run`.
- Building, signing or publishing the Flatpak; Flathub offline sources.
- Meeting the latency targets (measured only).

## Decisions

### D1. Voice is a core-side event consumer and command producer
`VoiceService` (in `tony/core/voice/service.py`) is attached to `CoreRuntime` as an optional collaborator. It observes every published event (the runtime publishes through a fan-out: UI bridge + `voice.observe`) and produces commands back into the runtime queue (`send_message` with `origin: voice`, `confirm`).
- Speech: `turn_started{speaks}` opens a `TurnSpeech` for that agent; `token`/`progress` feed it; turn `result` finishes it; `error` source `front` aborts it.
- Confirmation: `needs_confirmation` during a speaking turn speaks the question and arms answer-listening; `tool_call` or task `result` for that `task_id` disarms it.
- Alternatives: (a) voice in the Qt layer — rejected: puts CPU-heavy threads and conversation rules in the UI, duplicates the speak decision; (b) Conversation calling a speaker port — rejected: couples the turn logic to audio and makes cancellation paths double. The event-driven seam reuses existing events plus `turn_started`.
- `voice=None` (CLI, tests that do not care) keeps today's behaviour exactly.

### D2. Speak/write decision in the core, announced by `turn_started`
`reply_plan(mode, origin, voice_ready) -> (speaks, writes)` is a pure function in `tony/core/orchestrator/reply_plan.py`; `Conversation.handle(text, origin="text")` computes it after prefix splitting, before the model call, and publishes `turn_started`. The voice-readiness probe is injected (`voice_ready: Callable[[], bool]`, default `lambda: False`), so `tony chat` always writes.
- Alternative: suppress `token` events in speak-only turns — rejected: changes the streaming contract the CLI and tests rely on; the chat presenter buffering on `writes: false` is local and reversible.
- The mode is fixed at turn start (matches existing prefix semantics).

### D3. Package layout and ports (`tony/core/voice/`)
Pure (mutated, offline tests): `ports.py` (Protocols `AudioInput.open(on_frame)/close()`, `AudioOutput.play(pcm, rate)/stop()`, `Vad.is_speech(window)/reset()`, `Stt.transcribe(pcm) -> str`, `Tts.synthesize(text, voice) -> Clip`; value objects; PCM as raw float32 LE `bytes`, so the core needs no numpy), `utterances.py` (assembler: 32 ms windows, 700 ms end silence, 30 s cut), `sentences.py` (incremental splitter), `spoken.py` (code/table substitution, markup stripping, long-reply gate), `answer.py` (`is_voice_yes`), `voices.py` (`kokoro/a,b` → `("a","b")`), `stages.py` (generic stage thread), `listener.py`, `speaker.py`, `service.py`.
Adapters (`tony/core/voice/engines/`, lazy imports, excluded from mutation, `voice`-marked tests): `sounddevice_io.py` (`RawInputStream` 16 kHz float32 blocksize 512; `OutputStream`/`play` at 24 kHz), `silero.py`, `faster_whisper.py`, `kokoro.py` (one `KPipeline`, voices cached by alias, blend = mean of loaded voice tensors), `loader.py` (`load_engines(config, voices) -> Engines | Unavailable(reason)`; import errors become `voice extra not installed: uv sync --extra voice`).

### D4. Threads and marshalling
- Capture: PortAudio callback thread → bounded frame queue. `tony-vad`: windows → assembler → utterance queue. `tony-stt`: transcribe → `post(callback)`. `tony-tts`: sentence queue → clip queue. `tony-playback`: plays clips in order.
- `post` is `loop.call_soon_threadsafe`; every event is published from the core loop thread only (single-writer invariant kept).
- `StageThread(name, handle, on_error)` wraps each loop: per-item `try/except` → `post(error("voice.<stage>", msg))`, item dropped, loop continues; `stop()` puts a sentinel and joins with a timeout (2 s each) on runtime shutdown.
- Cancellation of speech: a generation counter; `stop_speaking()` bumps it, clears both queues and calls `AudioOutput.stop()`; items tagged with an older generation are discarded by TTS and playback threads.
- Preload runs in a `tony-voice-load` thread at runtime start: VAD, STT model, then the voices of the front, worker and guard agents (de-duplicated), publishing `loading` → `ready`/`unavailable`.

### D5. Spoken text pipeline (pure)
`TurnSpeech(agent_voice, say)` = `SentenceSplitter` → `SpokenFilter` → `LongReplyGate`:
- Splitter: buffers streamed text; a sentence ends at `[.!?…]` followed by whitespace (so `3.5` and `notas.md` are not cut) or at `\n`; `finish()` flushes the remainder. Fence/table detection works on line starts: a line is classified once its first 3 non-space characters (or its newline) are known.
- Filter: lines inside ``` fences and lines starting with `|` become one `Te lo dejo en pantalla.` item per block; consecutive phrase items collapse; inline markup is stripped (`**`, `__`, `*`, `_` emphasis, leading `#`/list markers, backticks, `[t](u)` → `t`); items empty after stripping are dropped.
- Gate: counts raw reply characters; items 1–2 pass immediately; items 3+ are held until `finish()` with total ≤ 600 (released) or total > 600 (dropped, phrase appended unless the last spoken item already is the phrase).
- Confirmation question: `re.sub(r" Regla: .*?\. ¿Autoriza\?$", " ¿Autoriza?", q)`; spoken with the guard voice, no gate.

### D6. Listening sessions
`Listener.start(purpose, idle_timeout_s)`: `message` (user/`--focus`, 10 s no-speech timeout) or `confirmation` (no idle timeout; closed when the request resolves). Starting always calls `stop_speaking()` first; for `confirmation` the service waits until the speaker queue is drained (question played) before opening the mic. One utterance per session; the mic is closed as soon as the utterance ends. The transcript routes by purpose: `confirmation` → `confirm{task_id, allow|deny}` via `is_voice_yes`; `message` → `transcript` event + `send_message{origin: voice}`. While a confirmation is armed, a user-started session is upgraded to the confirmation purpose.
- `is_voice_yes`: NFD, drop combining marks, casefold, drop Unicode punctuation (`P*`), collapse whitespace, equals `si edith`.
- Alternative: continuous listening with VAD gating — rejected: records while Tony speaks (no echo cancellation), privacy cost, and barge-in is out of scope.

### D7. Commands and events
- `SendMessage.origin: Literal["text","voice"] = "text"`; new `Listen`, `StopListening` commands. `listen` while not `ready` → `error("listen", reason)`; while `loading` it is remembered and started on `ready` (needed for `tony --focus` at launch).
- Events: `turn_started`, `transcript`, `voice_state` builders in `core_events.py`. `audio_chunk` stays unpublished.
- `cancel` additionally calls `voice.stop_speaking()` and `voice.stop_listening()`.

### D8. Desktop integration (presenters + thin adapters)
- Presenters (mutated): `VoicePresenter` (mic enabled/label/tooltip, `toggle()` → `listen`/`stop_listening`), `TrayPresenter` (state machine per spec), `ConfirmationAttention` (decides "notify" from `needs_confirmation` + injected `window_hidden()`), `ChatPresenter` gains `turn_started`/`transcript` handling.
- `tony/apps/desktop/system/` (OS adapters, excluded from mutation): `tray.py` (`QSystemTrayIcon`, icons painted as filled circles, no asset files), `single_instance.py` (`QLocalServer`/`QLocalSocket`), `hotkey.py` (pynput `GlobalHotKeys`, callback → Qt signal), `notifier.py` (desktop-notifier on its own `tony-notify` thread + asyncio loop; click → Qt signal). Pure helpers they use are separate modules: `hotkey_spec.py` (`Super+J` → `<cmd>+j`; modifiers Super/Meta/Win, Ctrl, Alt, Shift; key = one character or `F1`–`F12`/`Space`/`Enter`/`Tab`/`Esc`), `instance_channel.py` (socket path, message parsing).
- `MainWindow.reveal(edith: bool)`: `showNormal`, `raise_`, `activateWindow`; with `edith` expands the Edith zone and focuses «Denegar».
- `app.launch(root, *, focus=False)`: first tries the channel (`show`/`focus`) and returns 0 if an instance answered; otherwise starts the app, serves the channel, creates tray/hotkey/notifier per config, and on `focus` reveals the window and submits `listen`.

### D9. Single-instance channel
Socket path `$XDG_RUNTIME_DIR/app/$FLATPAK_ID/tony.sock` inside Flatpak, else `$XDG_RUNTIME_DIR/tony-desktop.sock`; fallback name `tony-desktop-<uid>` with `QLocalServer.SocketOption.UserAccessOption` when `XDG_RUNTIME_DIR` is unset. `XDG_RUNTIME_DIR` is mode 0700 and per user. Stale socket: client connect fails → `QLocalServer.removeServer(path)` then `listen`. Protocol: one UTF-8 line, exactly `show` or `focus`; anything else (or > 16 bytes) is ignored. Client timeout 500 ms.

### D10. CLI
Root callback option `--focus` (bool). With a subcommand it is a usage error. `desktop_launcher` receives `focus` so CLI tests stay Qt-free.

### D11. Packaging
- Runtime `org.kde.Platform//6.8` / `org.kde.Sdk//6.8` (Python 3.12, Qt platform plugins and portals for a PySide6 app).
- Modules: `portaudio` (v19.7.0 tarball, `sha256` pinned, `--disable-static`), `tony` (`buildsystem: simple`, source `type: dir, path: ..`): `pip3 install --prefix=/app --no-deps --require-hashes -r packaging/requirements.txt` (generated by `uv export --frozen --no-dev --extra voice --extra desktop --no-emit-project`, CPU torch index as `--extra-index-url`), then `pip3 install --prefix=/app --no-deps .`, then install `.desktop` and SVG icon to `share/applications` and `share/icons/hicolor/scalable/apps`.
- PyPI downloads need `build-options.build-args: [--share=network]` — accepted for local builds only (Flathub out of scope); integrity comes from `--require-hashes`.
- Validation without building: a default-suite test parses the YAML and the `.desktop` file and asserts ids, command, exact finish-args, the PortAudio `sha256` and `--require-hashes`; final verification additionally runs `desktop-file-validate` and `flatpak-builder --show-manifest` when installed.

### D12. Dependencies and test isolation
- `[project.optional-dependencies]`: `voice = [faster-whisper, kokoro, silero-vad, torch, sounddevice, numpy]`, `desktop = [desktop-notifier, pynput]`; `[tool.uv.sources] torch = {index = "pytorch-cpu"}` with an explicit `https://download.pytorch.org/whl/cpu` index.
- Only `engines/*` and `apps/desktop/system/{notifier,hotkey}.py` import these packages, lazily. A layout test asserts no other module imports them.
- `do_not_mutate` gains `tony/core/voice/engines/*` and `tony/apps/desktop/system/*` (OS glue; logic is in mutated pure modules).
- Fakes in `tests/fakes/voice.py`: `ScriptedAudioInput` (frames list, optional raise on open), `ThresholdVad` (first float > 0.5 = speech), `ScriptedStt`, `TextTts` (encodes the text in the clip), `RecordingAudioOutput` (records clip texts and blocks optionally), `FakeNotifier`, `FakeHotkeys`.

### D13. Latency benchmark
`tests/voice/test_latency.py` (marker `voice`): 5 runs each; voice leg = real VAD/STT/TTS/playback-to-null output with a synthesised Spanish WAV and a chat engine that is the real Claude engine when `TONY_EVALS=1`, else a fake streaming a fixed reply; text leg only with `TONY_EVALS=1`. Prints and `record_property`s p50; never asserts the targets.

## Risks / Trade-offs

- [Voice round trip far above 2 s on this CPU] → preload everything, `beam_size=1`, sentence streaming; benchmark reports the real number; no gate.
- [CPU contention between STT and TTS] → torch/whisper threads capped at half the cores each.
- [Wayland compositors refuse focus stealing on `activateWindow`] → `--focus` still shows/restores and starts the mic; README documents the custom shortcut; X11 hotkey only.
- [No system tray on some GNOME setups] → tray skipped; window close still quits.
- [`bf_emma` is an English voice; the blend may sound accented] → required by spec for a distinct Edith; Spanish phonemes come from lang `e`.
- [Notification shows the question (masked args) possibly on a lock screen] → masked by `MaskingPublisher`; documented. Security-relevant.
- [Local IPC triggers the microphone] → user-only socket, two-message whitelist, visible «Escuchando…» state, one utterance and 10 s idle cap. Security/privacy-relevant.
- [PortAudio missing on the host] → voice `unavailable` with reason; README names the package; Flatpak builds it.
- [Large Flatpak due to torch] → accepted; CPU wheels only.
- [Thread tests flaky] → fakes are synchronous per item, waits use explicit timeouts (≤ 5 s), no sleeps for ordering.

## Migration Plan

- Additive: without the extras the app behaves as before except the mic tooltip shows the reason. Bundled voices change for Viernes and Edith (user-edited `agent.md` files keep working: the blend syntax is a superset).
- Rollback: revert the change; persisted `reply_mode` lines stay valid.
