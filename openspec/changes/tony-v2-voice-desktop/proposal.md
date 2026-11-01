# Proposal

## Why

Tony v2 converses, delegates and guards every tool call from a native window, but it is still text-only: the reply mode is stored without producing audio, the microphone button is a disabled placeholder, and the app cannot be summoned from the desktop, signal pending confirmations while hidden, or be packaged. This last phase closes the v2 rebuild by adding local voice in and out, desktop integration and a Flatpak manifest.

## What Changes

- **Local voice I/O in the core**: capture 16 kHz mono float32 with `sounddevice`, Silero VAD (utterance ends after 700 ms of silence, cut at 30 s), faster-whisper `small` `int8` CPU in Spanish, Kokoro (lang `e`) playback at 24 kHz. Each stage runs in its own thread; any stage failure is published as an `error` event and never closes the window. The STT model and the three agents' voices are preloaded at app start. Every engine sits behind a port with an offline fake.
- **One voice per agent**: Jarvis `kokoro/em_alex`, Viernes `kokoro/ef_dora`, Edith `kokoro/ef_dora,bf_emma` (comma = averaged Kokoro voice blend). `voice.tts` accepts a comma-separated blend.
- **Voice turns**: a transcribed utterance becomes a user message exactly like typed text, tagged with origin `voice`. Replies are split into sentences while streaming and each sentence is synthesised and played as soon as it is complete.
- **Reply modes now act**: `voice` speaks only, `text` writes only, `both` does both, `auto` speaks when the message came by voice and writes otherwise; when voice is unavailable every turn writes. In speak-only turns the chat still receives the full reply once the turn ends.
- **Spoken-content rules**: fenced code blocks and Markdown tables are replaced in the spoken stream by «Te lo dejo en pantalla.»; replies longer than 600 characters are spoken as their first two sentences followed by that phrase; Markdown markup is never read aloud.
- **Edith by voice**: in a speaking turn a pending confirmation is spoken with Edith's voice and the next utterance answers it: normalised `si edith` is yes, anything else is no, silence until `confirm_timeout_s` is a timeout.
- **Microphone button enabled**: starts/stops listening for one utterance; new commands `listen` and `stop_listening`; `send_message` gains `origin`.
- **New core events**: `turn_started`, `transcript`, `voice_state`. `audio_chunk` stays reserved and unpublished (audio never leaves the core).
- **Desktop integration**: `QSystemTrayIcon` with show/hide and quit and the state `idle`/`working`/`awaiting_confirmation` in tooltip and icon; single instance via `QLocalServer`; `tony --focus` raises the running window and starts the microphone (or launches the app); global hotkey `desktop.hotkey` via `pynput` only on X11; native notification via `desktop-notifier` for a pending confirmation while the window is hidden or minimised, whose click raises the window on the Edith banner.
- **Packaging**: `packaging/` gets the Flatpak manifest `io.github.renzoramosdev.Tony` with the required finish-args, a `.desktop` file and an icon; the README documents building it, Wayland shortcuts and that `npx` MCPs need Node (recommend `uvx`).
- **Latency benchmark**: a `voice`-marked test reports p50 of text first token and voice first audio without failing.
- **Dependencies**: optional extras `voice` (faster-whisper, kokoro, silero-vad, torch CPU, sounddevice, numpy) and `desktop` (desktop-notifier, pynput); the default test suite installs neither.

## Capabilities

### New Capabilities
- `voice-io`: audio capture and playback, VAD segmentation, STT, TTS with per-agent voices and blends, preloading, stage threads, failure isolation, availability and the optional extra.
- `voice-conversation`: voice turns, sentence-streamed speech, reply-mode speak/write decisions, spoken-content rules, Edith confirmation by voice and the latency benchmark.
- `desktop-integration`: tray icon and state, single instance and `tony --focus`, X11 global hotkey, native confirmation notifications.
- `flatpak-packaging`: the Flatpak manifest, `.desktop` file, icon and their documentation.

### Modified Capabilities
- `desktop-app`: microphone button enabled and driven by voice state; chat handles `turn_started` and `transcript`; command queue gains `listen`, `stop_listening` and `send_message.origin`; cancel also stops speech and listening.
- `core-events`: conversation event types gain `turn_started`, `transcript` and `voice_state`; `audio_chunk` remains reserved.
- `front-conversation`: reply mode is no longer storage-only; each turn publishes `turn_started` with origin and speak/write decisions.
- `agent-definitions`: `voice.tts` voice-blend syntax; bundled Viernes voice `kokoro/ef_dora`.
- `guard-policy`: bundled Edith voice `kokoro/ef_dora,bf_emma`.
- `chat-cli`: `tony agents` rows show the new bundled voices.

## Impact

- Code: `tony/core/voice/` (ports, utterance assembler, sentence splitter, spoken text, voice answer, service, stage threads, `engines/` adapters), `tony/core/orchestrator/{commands,conversation,runtime}.py`, `tony/core/events/core_events.py`, `tony/core/loader/agent_md.py`, `tony/apps/desktop/` (presenters for voice and tray, chat presenter, main window, tray, single instance, hotkey and notifier adapters, `app.py`), `tony/apps/cli/main.py` (`--focus`).
- Data: `agents/viernes/agent.md` and `agents/edith/agent.md` voices; `packaging/` manifest, desktop file, icon and pinned requirements.
- Dependencies: `pyproject.toml` extras `voice` and `desktop`, CPU-only torch index; `uv.lock`; mutmut exclusions for engine and OS adapters.
- Systems: PortAudio (system library on the host, built as a module in the Flatpak), a D-Bus notification server, an X11 session for the hotkey.
- Out of scope: wake word, barge-in, offline mode, building or publishing the Flatpak, AppImage, `tony doctor`.
