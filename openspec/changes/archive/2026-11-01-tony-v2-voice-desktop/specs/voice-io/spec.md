# Spec Delta

## Purpose

Defines Tony's local voice input and output in the desktop app: microphone capture, end-of-utterance detection, Spanish speech-to-text, per-agent text-to-speech and playback, their preloading, threading and failure isolation.

## ADDED Requirements

### Requirement: Audio formats
Microphone audio SHALL be captured locally as 16 kHz mono float32 samples and synthesised speech SHALL be played locally at the speech engine's sample rate (24 kHz). Audio SHALL NOT leave the process, SHALL NOT be written to disk and SHALL NOT be published as an event.

#### Scenario: Capture format
- **WHEN** the microphone is opened for listening
- **THEN** it is opened as one channel of float32 samples at 16000 Hz

#### Scenario: Playback rate
- **WHEN** a sentence synthesised by the speech engine is played
- **THEN** it is played at 24000 Hz and no `audio_chunk` event is published

### Requirement: Listening for one utterance
A listening session SHALL capture audio until one utterance ends, then stop the microphone. A session SHALL also stop on `stop_listening`, on `cancel`, and, when started by the user, after 10 s without any speech. Starting a session SHALL first stop any speech being played, so Tony never records its own voice.

#### Scenario: One utterance per activation
- **WHEN** the user starts listening, speaks one sentence and stays silent
- **THEN** one utterance is transcribed and the microphone is closed

#### Scenario: No speech
- **WHEN** the user starts listening and nothing is said for 10 s
- **THEN** the microphone is closed and nothing is transcribed

#### Scenario: Listening interrupts playback
- **WHEN** Tony is speaking and the user starts listening
- **THEN** playback stops before the microphone opens

### Requirement: End of utterance
Speech SHALL be detected by a voice activity detector over 32 ms windows. An utterance SHALL end after at least 700 ms of continuous non-speech following speech, and SHALL be cut when its duration reaches 30 s. Leading and trailing non-speech SHALL NOT be transcribed.

#### Scenario: Silence closes the utterance
- **WHEN** 1 s of speech is followed by 704 ms (22 windows) of silence
- **THEN** one utterance of the speech windows is produced

#### Scenario: Short pause continues the utterance
- **WHEN** speech, 640 ms of silence and more speech arrive
- **THEN** they form a single utterance

#### Scenario: Maximum duration
- **WHEN** the user speaks without pause for 40 s
- **THEN** an utterance is produced when 30 s are reached

### Requirement: Speech to text
Each utterance SHALL be transcribed in Spanish (`es`) by faster-whisper with the model named in `voice.stt` (`faster-whisper/small` by default), `int8` compute on CPU. A transcript that is empty after trimming SHALL be discarded without starting a turn.

#### Scenario: Utterance transcribed
- **WHEN** an utterance saying «¿Qué hora es?» ends
- **THEN** the transcript `¿Qué hora es?` is produced with language `es`

#### Scenario: Noise only
- **WHEN** an utterance is transcribed as an empty or whitespace-only text
- **THEN** no message is sent and listening ends

### Requirement: Text to speech per agent
Sentences SHALL be synthesised with Kokoro, language code `e`, using the voice in `voice.tts` of the agent that speaks them. A comma-separated voice list SHALL be synthesised with the element-wise average of those Kokoro voices.

#### Scenario: Jarvis voice
- **WHEN** a Jarvis sentence is synthesised with the bundled agents
- **THEN** the Kokoro voice `em_alex` is used

#### Scenario: Edith blend
- **WHEN** an Edith sentence is synthesised with the bundled agents
- **THEN** the voice used is the average of the Kokoro voices `ef_dora` and `bf_emma`

### Requirement: Preloading at app start
When the desktop app starts, the voice activity detector, the speech-to-text model and the voices of the front, worker and guard agents SHALL be loaded in the background without blocking the window. A `voice_state` event SHALL report `loading` and then `ready`, or `unavailable` with a reason.

#### Scenario: Preload succeeds
- **WHEN** the app starts with the voice engines installed
- **THEN** `voice_state` `loading` is published, the three voices and the model are loaded once, and `voice_state` `ready` follows

#### Scenario: Window not blocked
- **WHEN** preloading takes several seconds
- **THEN** typed messages are answered meanwhile

### Requirement: Voice unavailable
When the voice engines are not installed, a voice setting is unsupported (`voice.stt` not `faster-whisper/<model>`, `voice.vad` not `silero`) or preloading fails, voice SHALL be unavailable: `voice_state` `unavailable` SHALL name the reason, every turn SHALL be written and the app SHALL keep working.

#### Scenario: Extra not installed
- **WHEN** the app starts without the voice extra installed
- **THEN** `voice_state` is `unavailable` with a reason naming the voice extra and typed conversation works

#### Scenario: Unsupported STT setting
- **WHEN** `config/tony.yaml` sets `voice.stt: vosk/es`
- **THEN** `voice_state` is `unavailable` with a reason naming `voice.stt`

### Requirement: Stage threads and failure isolation
Capture, voice activity detection, speech-to-text, synthesis and playback SHALL each run outside the UI thread and the core event loop, in their own threads. A failure in any stage SHALL publish an `error` event with source `voice.<stage>` and SHALL NOT close the window or stop the other stages; the failed item SHALL be dropped.

#### Scenario: Synthesis failure
- **WHEN** synthesising the second sentence of a reply raises an error
- **THEN** an `error` event with source `voice.tts` is published, the third sentence is still played and the window stays open

#### Scenario: Microphone missing
- **WHEN** the user starts listening and no input device exists
- **THEN** an `error` event with source `voice.capture` is published and `voice_state` returns to `ready`

### Requirement: Voice stops with the app
Closing the app SHALL stop listening and playback and end every voice thread before the process exits.

#### Scenario: Close while speaking
- **WHEN** the user closes the window while a reply is being spoken
- **THEN** playback stops and no voice thread is alive when the app exits

### Requirement: Optional voice dependencies
The voice engines and audio library SHALL be installable as an optional extra; the default installation and the default test run SHALL NOT require them. Tests using the real engines SHALL be marked `voice` and excluded by default.

#### Scenario: Default test run
- **WHEN** `uv run pytest` runs without the voice extra installed
- **THEN** it passes and no `voice`-marked test runs
