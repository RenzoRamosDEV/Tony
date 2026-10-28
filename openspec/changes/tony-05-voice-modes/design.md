# Design

## Context

- Estado de partida (entregas 01–04): `ChatSession.handle(text, modality="text")` ya resuelve el modo con `resolve_reply_mode(prefix, persisted, yaml_default, input_modality)` (`auto` → `voice` si `modality == "audio"`), pero la modalidad no llega al preámbulo (`build_turn_preamble(now, mode, style, preferences_block)`) y ningún adaptador la pasa distinta de `"text"`. `FrontTurn {text, structured, usage, error}`; `parse_front_reply` produce `{display_text, speech_text}` con `speech_text = None` en `text`. `AssistantReply` lleva `display_text`, `speech_text`, `mode`, `message_id`, `usage`, `error`.
- `TonySettings.voice = VoiceSettings {stt: "faster-whisper/small", tts: "kokoro/ef_dora", vad: "silero"}` ya existe y no cambia. `pyproject.toml` declara `voice = []` vacío y solo el marcador `evals`. `tony doctor` ya tiene `check_voice(env)` (informativo: `find_spec` de `faster_whisper`/`kokoro` y `which("espeak-ng")`).
- Web (entrega anterior): `tony/apps/web/{protocol,hub,ws_channel,server,confirmations,api}.py`; `parse_client_message` responde `not_implemented` a `audio.*`; el bucle de `/ws/chat` solo lee texto; `ConversationHub.user_text(text)` crea el turno; `WebChannel.send(AssistantReply)` publica `usage` + `assistant.final`; `ConversationStream` numera `seq` y guarda 500 sobres; `OutboundQueue` es de sobres JSON; uvicorn con `ws_max_size = 65536`; `/api/health` devuelve `{status, version, front, worker, mcp}`. Frontend React + Vite + TypeScript con `ChatSocket`, reductor puro y `App`.
- Streaming honesto (decisión de la entrega anterior): `ClaudeSdkConversation` no entrega fragmentos; `on_text` existe pero solo lo alimenta `FakeConversationRunner`. Consecuencia para la voz: con el motor real el texto hablado completo llega al final del turno; el "audio antes de terminar" se materializa como frases sintetizadas y reproducidas mientras las siguientes se generan (ver D5).
- Reglas de arquitectura (`tests/test_architecture.py`): `tony.core` no importa `tony.apps`, `typer`, `fastapi`; `runner`/`orchestrator`/`memory` no importan `channels`.
- Entorno verificado: CPU AMD Ryzen 5 7535U (12 hilos, 14 GB, sin GPU); `faster-whisper` 1.2.x (`device="cpu", compute_type="int8"`); `kokoro` 0.9.4 (Python < 3.13, `torch`, `misaki`; español requiere `espeak-ng`, presente en `/usr/bin/espeak-ng`; voces `lang_code="e"`: `ef_dora`, `em_alex`, `em_santa`; salida 24 kHz); `silero-vad` 6.x con `onnxruntime` (16 kHz, ventanas de 512 muestras); modelos en la caché de Hugging Face.
- Motivación y alcance: proposal.md. Comportamiento exigido: `specs/*/spec.md` de este cambio.

## Goals / Non-Goals

**Goals:**
- `tony.core.voice` como núcleo sin framework: puertos (`Vad`, `Stt`, `Tts`), lógica pura (segmentación de intervenciones, segmentación de frases, limpieza de markdown, pipeline de salida) probada sin motores; los motores reales viven en `tony.core.voice.engines` y solo se importan de forma perezosa.
- La web es un adaptador: `audio_ws.py` traduce frames y mensajes `audio.*` a los puertos; `tts_stream.py` traduce el pipeline a `tts.*`. `ChatSession` y el protocolo de texto no cambian de comportamiento.
- Suite estándar determinista (< 60 s) con `FakeVad`/`FakeStt`/`FakeTts` y WAV sintéticos; motores reales solo bajo `-m voice`.
- Latencia: trabajo de CPU acotado a 2 hilos, modelos cargados una vez, frase a frase para que el primer audio no espere al resto.

**Non-Goals:**
- Fragmentos reales de texto desde el SDK (queda como en la entrega anterior); VAD en el cliente; `stt.partial`; wake word; barge-in; voz en CLI; idiomas distintos de `es`/`en`; GPU.

## Decisions

### D1. Layout de módulos y reglas de dependencia

```
tony/core/voice/
  __init__.py       reexporta puertos, dobles no; `voice_availability(settings) -> VoiceAvailability`
  ports.py          Utterance {pcm: np.ndarray f32 16k, duration_ms}, Transcript {text, language, duration_ms},
                    AudioChunk {pcm16: bytes, sample_rate: 24000}, Protocols Vad/Stt/Tts, SpeechSink
  utterances.py     UtteranceAssembler: aplica 700 ms / 300 ms / 30 s a una secuencia de ventanas clasificadas
  segmenter.py      SentenceSegmenter (incremental): feed(text) -> list[str], flush() -> str | None
  cleanup.py        speech_text_for(display_text, speech_text) -> SpeechText {text, truncated, stripped}
  pipeline.py       SpeechPipeline: frases -> Tts -> SpeechSink, cancelación, degradación, métricas
  executor.py       VoiceExecutor: ThreadPoolExecutor(max_workers=2) + run(fn, *args) en el bucle
  aliases.py        parse_alias("kokoro/ef_dora") -> (engine, name); KOKORO_SPANISH_VOICES; WHISPER_MODELS
  engines/
    __init__.py     EngineRegistry: singletons perezosos por proceso (load_vad/load_stt/load_tts), warmup()
    silero.py       SileroVad(Vad)        (importa silero_vad/onnxruntime dentro de la función de carga)
    faster_whisper.py FasterWhisperStt(Stt)
    kokoro.py       KokoroTts(Tts)
tony/apps/web/
  audio_ws.py       AudioSession: audio.start/chunk/end -> Vad -> Stt -> stt.final; límites; estado por hub
  tts_stream.py     SpeechStreamer(SpeechSink): SpeechPipeline -> tts.start/chunk.meta/[bin]/end/cancelled
  protocol.py       += tipos audio.*/stt.*/tts.*, BinaryFrame, publish_binary (sin seq)
  hub.py            += audio_start/audio_frame/audio_end, user_text(text, modality, message_id), cancel(message_id)
  server.py         += bucle receive() texto/binario; health.voice; shutdown cancela voz
  frontend/src/audio/  capture.worklet.ts, capture.ts, player.ts, level.ts
  frontend/src/components/ MicButton.tsx, StopAudioButton.tsx, VoiceStatus.tsx
tony/apps/cli/voice_cli.py  sub-app `voice`: warmup, bench
tests/fakes/voice.py        FakeVad, FakeStt, FakeTts, ListSpeechSink
tests/fixtures/audio/       generate.py + WAV sintéticos cortos (≤ 3 s)
```

- Reglas nuevas en `tests/test_architecture.py`: `faster_whisper`, `kokoro`, `silero_vad`, `onnxruntime`, `torch` solo en `tony.core.voice.engines`; `tony.core.voice` no importa `tony.apps`, `fastapi` ni `tony.core.channels`; `tony.apps.web.audio_ws`/`tts_stream` no importan motores (reciben los puertos).
- Alternativa descartada: meter VAD/STT/TTS en `tony.apps.web`. Rechazada: el bench, el doctor y una futura entrada por Telegram (nota de voz) necesitan los mismos puertos sin FastAPI.

### D2. Formatos de audio y política de segmentación (decisión fijada)

- Entrada: frames binarios WS con PCM Float32 little-endian, 16 kHz, mono, 20–40 ms (320–640 muestras; 1 280–2 560 bytes). Límite por frame 16 KiB (`audio_frame_too_large`, sin cerrar). `audio.start` solo acepta `{16000, 1, "f32"}`; otra cosa → `unsupported_audio`.
- VAD en el servidor con Silero: `AudioSession` acumula muestras y entrega ventanas de 512 muestras (32 ms) al clasificador; probabilidad ≥ 0,5 = habla. `UtteranceAssembler` (puro, compartido por `SileroVad` y `FakeVad`) aplica: fin de intervención tras ≥ 700 ms de ventanas sin habla después de habla; descarte si la habla acumulada < 300 ms; corte forzado al alcanzar 30 s de intervención (el resto inicia otra); `audio.end` hace `flush()` de lo pendiente (≥ 300 ms de habla → intervención).
- Una intervención de audio a la vez por conversación: `audio.start` con otra abierta → `audio_in_progress`; frame o `audio.end` sin abrir → `audio_not_started`; cierre del socket descarta el estado sin transcribir.
- Salida: PCM Int16 little-endian, 24 kHz, mono; cada frame binario va precedido de `tts.chunk.meta {message_id, seq, sentence_index}`. Los binarios no consumen `seq` de conversación ni entran en el búfer de reenvío (el audio perdido en una reconexión no se recupera; el texto sí).
- Alternativa descartada: VAD en el navegador (menos tráfico). Rechazada: duplica la lógica de segmentación en dos lenguajes y el servidor ya tiene que validar los límites.

### D3. Motores, carga única y ejecutor dedicado (decisión fijada)

- `VoiceExecutor`: `ThreadPoolExecutor(max_workers=2, thread_name_prefix="tony-voice")` único por proceso; `await executor.run(fn, *args)` = `loop.run_in_executor`. STT y TTS nunca se llaman directamente desde el bucle. `close()` hace `shutdown(wait=False, cancel_futures=True)`.
- `EngineRegistry` (módulo `engines/__init__.py`): `get_vad()`, `get_stt(model)`, `get_tts(alias)` con `threading.Lock` y carga perezosa; `warmup(settings)` carga los tres y devuelve tiempos. Las importaciones de `faster_whisper`, `kokoro`, `silero_vad` ocurren dentro de las funciones de carga (el módulo se importa sin el extra).
- `SileroVad`: `load_silero_vad(onnx=True)` (onnxruntime CPU); `classify(window_512) -> float`; estado del modelo reiniciado por intervención (`reset_states`). `FasterWhisperStt`: `WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4)`; `transcribe(pcm, language=lang, beam_size=1, vad_filter=False, condition_on_previous_text=False)`; concatena segmentos. `KokoroTts`: `KPipeline(lang_code="e")`; `pipeline(text, voice=name)` → por cada trozo convierte float32 24 kHz a Int16 y lo cede como `AudioChunk` (iteración en el ejecutor, entrega al bucle con `asyncio.Queue`).
- Idioma: STT `language = front.persona.language` (`es` por defecto, `en` si el `front` es `en`). TTS: `lang_code="e"` fijo y voz del alias `voice.tts` en v1 (las voces `ef_dora`, `em_alex`, `em_santa`); un `front` en inglés se lee con la voz española (fuera de alcance mejorarlo).
- Alias: `parse_alias("motor/nombre")`; `faster-whisper/<model>` con `model ∈ WHISPER_MODELS` (`tiny`, `base`, `small`, `medium`, `large-v3`, variantes `.en`/`distil`); `kokoro/<voice>` con `voice ∈ KOKORO_SPANISH_VOICES`. Alias inválido → `VoiceConfigError` en español con el alias y los valores válidos (lo usa `doctor` sin importar motores).
- Dependencias del extra: `faster-whisper>=1.2,<2`, `kokoro>=0.9.4,<1`, `silero-vad>=6,<7`, `onnxruntime>=1.17,<2`, `numpy>=1.26,<3`, `soundfile>=0.12,<1`. `torch` llega como dependencia transitiva de `kokoro`; se fija la rueda CPU con `[tool.uv.sources] torch = {index = "pytorch-cpu"}` e índice `https://download.pytorch.org/whl/cpu` (`explicit = true`) para no descargar CUDA. Alternativa descartada: `silero-vad` con `torch` en vez de `onnxruntime`; `torch` ya está por Kokoro, pero `onnxruntime` arranca más rápido y mantiene el VAD utilizable si Kokoro se sustituye.

### D4. Entrada por audio en el hub y el bucle del socket

- `server.py`: el bucle de `/ws/chat` pasa a `message = await websocket.receive()` y distingue `message["text"]` (sobre JSON, mismo `parse_client_message`) de `message["bytes"]` (→ `hub.audio_frame(bytes)`); antes del `hello` un binario responde `hello_required`. `audio.*` ya no es `NotImplementedType`: `audio.start` y `audio.end` son tipos de cliente con payload validado.
- `ConversationHub` gana `audio: AudioSession | None` (uno por conversación) y `voice: VoiceAvailability`. `audio_start(payload)`: sin voz → `voice_unavailable`; abierta → `audio_in_progress`; si hay síntesis en curso → `speech.cancel()` (→ `tts.cancelled`); crea `AudioSession(vad=registry.get_vad(), stt=registry.get_stt(...), executor, language, on_final)`. `audio_frame(bytes)`: valida tamaño, `np.frombuffer(float32)`, `session.feed(pcm)` → por cada `Utterance` lanza `asyncio.Task` de transcripción en el ejecutor (en serie: una cola por sesión para preservar el orden). `audio_end()`: `flush()` y cierra.
- `on_final(transcript)`: si `text` vacío → nada; genera `message_id = uuid4().hex`, publica `stt.final {text, message_id}` y llama a `user_text(text, modality="audio", message_id=message_id)`; si hay turno en curso → `turn_in_progress` y se descarta.
- `ChatSession.handle(text, modality="text", message_id: str | None = None)`: el `message_id` opcional se usa para `_store_message("user", ..., message_id=...)` y `UserAccepted`; sin él se genera como hasta ahora (compatibilidad con la CLI y con `user.text`). `build_turn_preamble(now, mode, style, preferences_block, input_modality)` añade la línea `Modalidad de entrada: voice|text` (`audio` → `voice`).
- Log: `AudioSession` emite al sumidero de eventos de la sesión `stt.final {chars, duration_ms}` (nunca texto ni audio); la transcripción solo se persiste como mensaje de usuario por `ChatSession`.
- Alternativa descartada: transcribir solo en `audio.end` (sin VAD en servidor). Rechazada: el usuario tendría que pulsar para cerrar cada frase; F1 exige fin de frase automático.

### D5. Salida por frases: `SpeechPipeline` y `SpeechStreamer` (decisión fijada)

- `SpeechPipeline(tts, executor, voice, sink, segmenter)`: `feed(text_fragment)` alimenta `SentenceSegmenter`; cada frase completa entra en una `asyncio.Queue`; un consumidor único sintetiza en orden (una frase a la vez en el ejecutor, dejando el otro hilo para STT) y llama a `sink.chunk(seq, sentence_index, audio)`; `finish()` hace `flush()` del segmentador, espera a la cola y llama a `sink.end()`; `cancel()` vacía la cola, cancela la síntesis en curso y llama a `sink.cancelled()`; una excepción del `Tts` → `sink.failed(error)` + `sink.cancelled()` y se descartan las frases restantes. Al terminar o cancelar emite `tts {sentences, duration_ms, cancelled}` al sumidero de eventos.
- Punto de enganche: `WebChannel.send(AssistantReply)` → publica `usage` + `assistant.final` como hoy y, si `reply.mode ∈ {voice, both}` y la voz está disponible, llama a `SpeechStreamer.start(reply)` que crea una `asyncio.Task` con el pipeline alimentado con `speech_text_for(reply)` completo y `finish()`. `assistant.final` no espera a `tts.end`. En `text` no se hace nada. `CliChannel` sigue ignorando la voz.
- Streaming desde fragmentos: `SpeechStreamer.on_delta(message_id, text)` alimenta el pipeline cuando el motor entrega fragmentos de `speech_text`; en v1 el motor real no los entrega y los fragmentos de `AssistantDelta` son de `display_text`, así que no se alimentan al pipeline (evita leer markdown). Consecuencia visible con el motor real: `assistant.final` llega antes que el primer `tts.chunk`, y el audio de la primera frase suena mientras se sintetizan las siguientes. La prueba "motor con fragmentos" usa `FakeConversationRunner` con `speech_chunks` para cubrir el camino de streaming sin cambiar el protocolo.
- `SpeechStreamer(SpeechSink)` mapea: `start` → `tts.start {message_id}`; `chunk` → `tts.chunk.meta {message_id, seq, sentence_index}` + `stream.publish_binary(pcm16)` (encolado en la misma `OutboundQueue`, inmediatamente detrás de su `meta`, sin `seq`); `end` → `tts.end`; `cancelled` → `tts.cancelled`; `failed` → `error {code: "tts_failed", detail}`. Fallo al cargar el motor → `tts_failed` sin `tts.start`.
- Cancelación: `hub.cancel(message_id)` → `streamer.cancel(message_id)` (desconocido o ya terminado → `unknown_task`); `audio_start`, `user_text` aceptado y `aclose()` cancelan la síntesis en curso antes de continuar. `OutboundQueue` nunca fusiona ni descarta `tts.chunk.meta` ni binarios; al cancelar, los binarios aún encolados se purgan junto con sus `meta` (única operación de descarte, acotada por `message_id`).
- Alternativa descartada: sintetizar en `ChatSession` (núcleo). Rechazada: la CLI no tiene salida de audio y la cancelación por `cancel {message_id}` y por `audio.start` es responsabilidad del hub web; el núcleo aporta el pipeline, el adaptador decide cuándo arrancarlo.

### D6. Segmentador de frases y limpieza de markdown (decisión fijada)

- `SentenceSegmenter`: corta en `[.?!…;]` seguido de espacio/fin o en `\n\n`; no corta si el token anterior está en `ABBREVIATIONS = {"sr.", "sra.", "dr.", "dra.", "ud.", "uds.", "núm.", "etc.", "p. ej.", "ej.", "pág."}` (comparación en minúsculas sobre la última palabra, con soporte para `p. ej.` como bigrama), ni si el punto está entre dígitos (`10.5`), ni dentro de `10:30` (los dos puntos no cortan). `feed(text) -> list[str]` devuelve las frases completas y retiene el resto; `flush()` devuelve el resto no vacío. Las frases se entregan sin espacios exteriores.
- `speech_text_for(display_text, speech_text)`: si `speech_text` no es `None` ni vacío → tal cual. Si no: elimina bloques de código (```…``` y `~~~`), código en línea (conserva el texto), tablas (líneas que empiezan por `|`), encabezados (`#`), énfasis (`*`, `_`), enlaces (`[texto](url)` → `texto`), imágenes (eliminadas), listas (`-`, `*`, `1.` → texto del ítem), citas (`>`); colapsa espacios. Trunca a 600 caracteres en el último límite de palabra. Añade ` …te lo muestro en pantalla` si hubo truncado o si se eliminó algún bloque (código, tabla, imagen); un texto corto sin bloques eliminados no lleva cierre.
- Alternativa descartada: pedir siempre `speech_text` al modelo con un reintento. Rechazada: añade una llamada al modelo y latencia; la limpieza local es determinista y probada por tabla.

### D7. Frontend: captura, reproducción y estados (decisión fijada)

- `capture.worklet.ts` (`AudioWorkletProcessor`): recibe el audio del dispositivo a su frecuencia nativa, re-muestrea a 16 kHz (promedio de bloques + interpolación lineal; suficiente para voz), acumula 480 muestras (30 ms) y hace `port.postMessage(Float32Array)` (transferencia). `capture.ts` (`MicCapture`): `getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true}})`, `AudioContext` + `audioWorklet.addModule`, `start()/stop()`, `muted` (cuando es `true` los frames se descartan sin enviar), `onLevel(rms)`. `level.ts`: RMS del último frame.
- `player.ts` (`PcmPlayer`): `AudioContext({sampleRate: 24000})` creado en el primer gesto del usuario; `enqueue(seq, pcm16: ArrayBuffer)` convierte Int16 → Float32, crea `AudioBuffer`, lo programa en `max(nextStartTime, currentTime)` y avanza `nextStartTime += duration`; descarta `seq` ≤ último; `stop()` para las fuentes y vacía; `onDrain` cuando termina la última fuente. Sin huecos entre frases porque la programación es por tiempo absoluto.
- `ChatSocket`: `sendBinary(buffer)` y `onBinary(buffer)`; el reductor guarda el último `tts.chunk.meta` pendiente y `App` empareja el siguiente binario con él (`seq`, `message_id`); un binario sin `meta` pendiente se descarta.
- Estado de voz en el reductor (`voice: {available, reason, mic: "off" | "on", phase: "idle" | "listening" | "transcribing" | "speaking", speakingMessageId}`): `tts.start` → `speaking` (y `MicCapture.muted = true`); `tts.end` (al drenar) y `tts.cancelled` → vuelve a `listening`/`idle` y `muted = false`; `stt.final` → burbuja de usuario con icono de micrófono; "Transcribiendo…" cuando el nivel cae bajo el umbral durante 700 ms tras habla y aún no hay `stt.final` (heurística de UI; la segmentación real es del servidor).
- `MicButton` (`aria-pressed`, `aria-label` "Activar micrófono"/"Desactivar micrófono"; `disabled` + `title` con `voice.reason` y `uv sync --extra voice` cuando `voice.available === false`), `StopAudioButton` ("Detener audio": `player.stop()` + `cancel {message_id}`), `VoiceStatus` (texto de fase + indicador de nivel). `App` consulta `GET /api/health` al cargar para `voice`.
- Alternativa descartada: `MediaRecorder` + Opus. Rechazada: el servidor tendría que decodificar y el VAD necesita PCM; `AudioWorklet` da PCM y re-muestreo sin dependencias.

### D8. CLI `tony voice` y `tony doctor`

- `tony/apps/cli/voice_cli.py`: `typer.Typer()` registrado como `app.add_typer(voice_cli.app, name="voice")`. `warmup`: importa `EngineRegistry` dentro de un `try/except ImportError` → "Instala el extra de voz: uv sync --extra voice" y `Exit(2)`; imprime `✓ vad 120 ms`, `✓ stt 2 310 ms`, `✓ tts 1 850 ms`. `bench`: 5 repeticiones de `load` (registro nuevo en subproceso no; se mide la primera carga del proceso y se repite solo STT/TTS), `stt_3s` (fixture sintética de 3 s), `tts_12w` (frase fija de 12 palabras); con `TONY_EVALS=1`, `roundtrip`: `build_chat_runtime` + `ListChannel` + `SpeechPipeline` con `ListSpeechSink`, midiendo desde `Transcript` listo hasta el primer `chunk`; imprime p50/p95 por medida y marca `p50 > 2000 ms` como "objetivo no alcanzado".
- `tony doctor`: `check_voice` pasa a devolver: `voice` (info: instalado/no, con sugerencia `uv sync --extra voice`), `espeak-ng` (`✓` ruta o info con `rpm-ostree install espeak-ng` / `brew install espeak-ng`), `voice.stt`/`voice.tts` (✓ o ✗ con valores válidos; usa `aliases.parse_alias`, sin importar motores), `voice-models` (info: en caché o "ejecuta tony voice warmup"; comprueba la existencia de `models--Systran--faster-whisper-<size>` y `models--hexgrad--Kokoro-82M` en `HF_HUB_CACHE`/`~/.cache/huggingface/hub`). `validate_config` incluye la comprobación de alias (pura).

### D9. Configuración, salud y disponibilidad

- Sin claves nuevas en `tony.yaml`: `voice.stt`, `voice.tts`, `voice.vad` ya existen. `VoiceAvailability {available, reason, stt, tts}` se calcula una vez al arrancar `tony web` (`find_spec` de los módulos del extra + validación de alias), sin cargar modelos; `/api/health` la expone como `voice`. Un fallo al cargar un modelo en el primer uso se comunica por `voice_unavailable` (STT) o `tts_failed` (TTS) con el detalle, no tumba el servidor.
- Las comprobaciones de los dobles en las pruebas web: `build_test_app(..., voice=FakeVoice(vad=FakeVad(), stt=FakeStt("¿qué hora es?"), tts=FakeTts()))` inyecta un registro de motores falso en el hub; sin `voice` el hub arranca con `available: false`.

### D10. Estrategia de pruebas (sin motores reales por defecto)

- `pyproject.toml`: marcador `voice: pruebas con los motores de voz reales (uv run pytest -m voice)` y `addopts = "-m 'not voice'"` (un `-m voice` explícito lo sustituye). `tests/apps/web/conftest.py` sigue con `importorskip("fastapi")`; `tests/core/voice/test_engines_real.py` hace `pytest.importorskip("faster_whisper")` y lleva el marcador.
- Fixtures: `tests/fixtures/audio/generate.py` crea, de forma determinista, `speech_1500ms.wav` (tono 220 Hz modulado + 700 ms de silencio), `short_200ms.wav`, `noise_3s.wav`, `tone_3s.wav` (para el bench) y `silence_1s.wav`; se versionan (PCM 16 kHz mono Int16, ≤ 3 s, < 100 KB cada uno). Los casos de 30 s se generan en memoria en la prueba.
- Dobles (`tests/fakes/voice.py`): `FakeVad` (energía RMS > 0,01 = habla, sobre `UtteranceAssembler`), `FakeStt(text, language="es")` (devuelve el texto fijado; `FakeStt(fail=True)` lanza), `FakeTts(fail_at_sentence=None)` (seno de 440 Hz, 300 ms por frase, en 2 fragmentos), `ListSpeechSink`. `FakeConversationRunner` admite `speech_chunks` para el camino de streaming.
- Núcleo (`tests/core/voice/`): `test_utterances.py` (tabla 700/300/30 s, flush), `test_segmenter.py` (tabla de frases, abreviaturas, decimales, horas, incremental), `test_cleanup.py` (tabla de markdown, truncado, cierre), `test_pipeline.py` (orden de `seq`, cancelación, degradación en la 2.ª frase, fallo de carga, evento `tts`), `test_executor.py` (2 hilos, no bloquea), `test_aliases.py`, `test_engines_real.py` (`voice`). `tests/core/channels/test_chat_session.py` amplía `message_id` opcional y `input_modality` en el preámbulo; `tests/core/test_front_prompt.py` la línea nueva.
- Web (`tests/apps/web/`): `test_audio_ws.py` (`audio.start` ok/`unsupported_audio`/`audio_in_progress`/`voice_unavailable`, binario sin start → `audio_not_started`, binario antes de `hello` → `hello_required`, frame de 20 000 bytes → `audio_frame_too_large`, secuencia completa `stt.final` → `user.accepted {effective_mode: voice}` → `tts.*`, transcripción vacía, `/t` por voz, `turn_in_progress`, cierre del socket con intervención abierta), `test_tts_stream.py` (orden `meta`/binario, `seq`, cancelación por `cancel {message_id}` y por `audio.start`, `tts_failed`, modo `text` sin `tts.*`, `both`), `test_api_health.py` (+ `voice`), `test_ws_flow.py` (actualiza `audio.start` → ya no `not_implemented`), `test_ws_reconnect.py` (binarios no reenviados). Doctor y CLI: `tests/core/doctor/test_checks.py` (alias, espeak, modelos), `tests/apps/test_cli_voice.py` (`CliRunner`, registro falso: warmup, bench sin modelo, sin extra → 2).
- Frontend (Vitest, `jsdom`): `audio/player.test.ts` (programación contigua con `AudioContext` simulado, descarte de `seq` fuera de orden, `stop`), `audio/capture.test.ts` (`muted` descarta frames; nivel), `audio/resample.test.ts` (48 kHz → 16 kHz, 30 ms → 480 muestras), `protocol/reducer.test.ts` (fases de voz, `stt.final` como mensaje de usuario, `meta` pendiente), `components/MicButton.test.tsx` (`aria-pressed`, deshabilitado con tooltip, permiso denegado), `App.test.tsx` (silenciado durante `tts.*`, "Detener audio" envía `cancel`).
- Mutación (≤ 3 min): `tony/core/voice/{utterances,segmenter,cleanup,pipeline,aliases}.py`.

## Risks / Trade-offs

- [p50 < 2 s de ida y vuelta puede no alcanzarse en CPU: STT `small` int8 de 3 s ≈ 1–1,5 s + modelo + primera frase Kokoro ≈ 0,5 s] → `beam_size=1`, `cpu_threads=4`, primera frase corta; el bench reporta el valor real y el README documenta `voice.stt: faster-whisper/base` y `compute_type` como opciones; el objetivo se mide con modelos precargados.
- [`torch` arrastra ruedas CUDA de varios GB] → índice `pytorch-cpu` explícito en `uv` (D3); verificar en la tarea de dependencias que `uv sync --extra voice` no descarga `nvidia-*`.
- [Kokoro en español depende de `espeak-ng` en el sistema] → `doctor` lo detecta con sugerencia; fallo de carga → `tts_failed` con el detalle y la respuesta queda en texto.
- [El motor real no entrega fragmentos: la primera frase no suena hasta el final del turno] → documentado (D5) y en el README; el pipeline ya acepta fragmentos para cuando se activen.
- [Eco: Tony se oye a sí mismo] → captura silenciada en el cliente durante `tts.*` (D7) y `echoCancellation: true`; sin barge-in en v1.
- [Dos hilos compartidos entre STT y TTS] → STT y TTS de la misma conversación no coinciden en la práctica (la captura se silencia durante la reproducción); con `audio.start` se cancela la síntesis antes de transcribir.
- [Binarios en la `OutboundQueue` y backpressure] → cada frase genera pocos frames (< 10); la purga al cancelar es por `message_id`; si el socket no lee, la síntesis se detiene por backpressure como el resto de eventos.
- [Reconexión durante una respuesta hablada pierde audio] → aceptado: el texto se reenvía por `seq`; la UI muestra `display_text` completo.
- [`AudioWorklet` requiere contexto seguro] → `http://127.0.0.1` y `http://localhost` cuentan como seguros; `--allow-remote` sin HTTPS deja el micrófono inutilizable y el README lo avisa.
- [Descarga de modelos en el primer `audio.start`] → `tony voice warmup` documentado como paso de instalación; `doctor` avisa si la caché está vacía.
- [Pruebas `-m voice` lentas] → fuera de la suite estándar; límite `timeout = 120` por prueba marcada.

## Migration Plan

- Sin migración de datos: `tony.yaml` ya tiene `voice`; `memory/settings.json` y SQLite no cambian.
- Despliegue local: `rpm-ostree install espeak-ng` (o `brew`) → `uv sync --extra web --extra voice --group dev` → `uv run tony doctor --offline` → `uv run tony voice warmup` → `cd tony/apps/web/frontend && npm install && npm run build` → `uv run tony web --open` → sesión de cierre (hablar en `auto`, "respóndeme por escrito", `/v`, una tabla por voz) → `uv run tony voice bench`.
- Rollback: revertir el commit; `tony web` sin el extra vuelve a `voice_unavailable`/micrófono deshabilitado; borrar la caché de modelos es opcional (`~/.cache/huggingface/hub/models--Systran--faster-whisper-small`, `models--hexgrad--Kokoro-82M`).

## Desviaciones de implementación

- D1/D2: el audio viaja por el núcleo como `bytes` crudos (Float32 LE a 16 kHz en `Utterance.pcm`, Int16 LE a 24 kHz en `AudioChunk.pcm16`) en vez de `np.ndarray`: `numpy` solo existe en el extra, y así `tony.core.voice`, `tony.apps.web` y la suite estándar funcionan sin él; los motores convierten en su frontera. `utterances.py` añade `VadSegmenter(vad, assembler)`, que corta el PCM en ventanas de 512 muestras y llama a `classify`, compartido por `AudioSession`, `FakeVad` y las pruebas.
- D2: la fixture `speech_1500ms.wav` lleva 800 ms de silencio final (no 700): el umbral de 700 ms exige 22 ventanas completas de 32 ms (704 ms) y con 700 ms exactos la intervención solo se cerraba en `flush()`.
- D3: `torch` se declara explícitamente en el extra `voice` (`torch>=2.5,<3`) porque `[tool.uv.sources]` solo se aplica a dependencias directas; como transitiva de `kokoro` uv resolvía la rueda CUDA (+5 GB). Verificado: `torch==2.14.1+cpu`, ningún `nvidia-*`. `EngineRegistry.get_stt`/`get_tts` reciben el alias completo (`faster-whisper/small`, `kokoro/ef_dora`), no el nombre suelto. El puerto `Tts.synthesize` es un iterador síncrono que el pipeline consume frase a frase en el ejecutor (`takewhile` sobre la bandera de cancelación, sin `asyncio.Queue` por fragmento).
- D4: `VoiceRuntime` (`tony/apps/web/voice.py`) agrupa disponibilidad, registro y ejecutor; el hub lo recibe en `bind(runtime, voice)`; `ChatRuntime.emit` expone el JSONL de la sesión para `stt.final`/`tts`. Un `error` de petición (`turn_in_progress`, `seq: 0`, envío directo) puede adelantar al `stt.final` encolado: las pruebas aceptan ambos órdenes. `cancel` admite `task_id` o `message_id`, ambos opcionales a nivel de payload.
- D5: con el motor real (sin fragmentos) el orden es `assistant.final` → `tts.start` → `tts.chunk.meta` + binario → `tts.end`; el escenario "Secuencia de una respuesta por voz" de `voice-input` se ajustó a ese orden. El camino con fragmentos existe: `ConversationRunner.turn(prompt, on_text, on_speech)` y el mensaje de canal `AssistantSpeechDelta` (la CLI lo ignora; `ClaudeSdkConversation` no lo produce); `FakeConversationRunner` hace una pausa de 50 ms tras cada `speech_chunk` para que el pipeline sintetice antes del final, como haría un modelo que transmite. La purga de audio encolado se aplica también en la degradación por `tts_failed`. `OutboundQueue.drained()`/`done()` esperan a que la bomba termine de enviar el último sobre para que `aclose()` entregue `tts.cancelled` antes del cierre `1001` (presupuesto `DRAIN_BUDGET_S = 1`).
- D7: el worklet se empaqueta con `import workletUrl from "./capture.worklet.ts?worker&url"` (con `new URL(…, import.meta.url)` Vite no lo emitía como módulo); "Hablando…" y el silenciado se derivan de `phase === "speaking" || player.playing`, así `tts.end` se aplica al instante en el reductor y la UI espera al drenado del reproductor sin diferir sobres. El nivel del medidor se cuantiza a pasos del 2 % para no re-renderizar en cada frame. Un `error` mientras se transcribe devuelve la fase a "Escuchando…".
- D8: `bench` mide `load` con una sola muestra (la primera carga del proceso) y repite 5 veces `stt_3s` y `tts_12w`; la muestra de 3 s se genera en memoria (tono modulado, sin fixtures de `tests/`). `tony doctor` añade `Environment.model_cache` (`HF_HUB_CACHE` o `~/.cache/huggingface/hub`) y reporta `voice-models` siempre (✓ en caché, informativo si falta alguno).
- D10: `tests/core/voice/test_engines_real.py` hace los `importorskip` dentro de una fixture `autouse`, no a nivel de módulo: con `-m 'not voice'` la recolección ya no importa `torch`.

## Open Questions

- Resueltas durante la implementación: el `OnnxWrapper` de `silero-vad` 6.2 exige `torch.Tensor` (`SileroVad` envuelve con `torch.from_numpy`); `KPipeline` 0.9.4 cede `torch.FloatTensor` (el adaptador acepta tensor o `ndarray`); la primera carga de `WhisperModel("small")` int8 tarda ~1 s con el modelo en caché (Kokoro ~3,7 s). Los números reales están en el README.
