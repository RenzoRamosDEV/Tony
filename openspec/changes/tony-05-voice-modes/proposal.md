# Proposal

## Why

Tras la entrega anterior el chat web funciona por texto, pero los modos `auto`/`voice`/`both` no producen audio y los tipos `audio.*` del protocolo responden `not_implemented`: hablar a Jarvis y oírle (F1, RF-10/11/13/14) sigue sin existir. La fase 4 se cierra cuando la ida y vuelta por voz sin tools queda por debajo de 2 s (p50, modelos precargados) y el modo se cambia por botón, por frase y por prefijo.

## What Changes

- Nuevo subpaquete `tony.core.voice` con los puertos `Vad`, `Stt` y `Tts`, el segmentador de frases, la limpieza de markdown para voz y el pipeline de salida por frases; adaptadores reales `Silero` (VAD), `FasterWhisper` (STT `small`, CPU, int8) y `Kokoro` (TTS español, voz `ef_dora`) cargados una sola vez y ejecutados en un `ThreadPoolExecutor` dedicado de 2 hilos; dobles `FakeVad`, `FakeStt`, `FakeTts` para la suite estándar.
- Extra `tony[voice]` (`faster-whisper`, `kokoro`, `silero-vad`, `onnxruntime`, `numpy`, `soundfile`) y dependencia del sistema `espeak-ng`; sin el extra el servidor arranca con la voz deshabilitada y la UI muestra el micrófono desactivado con tooltip.
- Protocolo WS `v: 1` ampliado: `audio.start`/`audio.chunk` (frame binario Float32 16 kHz mono)/`audio.end` dejan de responder `not_implemented`; el servidor segmenta con VAD, transcribe y emite `stt.final {text, message_id}` que se procesa exactamente como `user.text`; salida `tts.start`, `tts.chunk.meta` + frame binario Int16 24 kHz, `tts.end`, `tts.cancelled`; errores `audio_not_started`, `voice_unavailable`, `tts_failed`.
- Salida por frases (RF-14): en `voice`/`both` el `speech_text` se trocea por frases y cada frase se sintetiza y envía mientras el turno sigue; si el modelo no produce `speech_text`, se sintetiza `display_text` limpio de markdown, código y tablas, truncado a 600 caracteres con cierre "…te lo muestro en pantalla" (RF-13). `cancel` o una nueva intervención → `tts.cancelled`; fallo de TTS → `error tts_failed` y la respuesta queda en texto.
- `auto` por modalidad de entrada (RF-11): la entrada por audio resuelve `auto` a `voice`; el bloque dinámico del `front` incluye `input_modality: voice|text`; `set_reply_mode` por frase sigue vigente y la UI lo refleja.
- Frontend: botón de micrófono (`aria-pressed`), captura con `AudioWorklet` a 16 kHz mono con re-muestreo, indicador de nivel, estados "Escuchando…"/"Transcribiendo…", reproducción con `AudioContext` a 24 kHz por cola de buffers sin cortes, captura silenciada mientras suena audio, botón "Detener audio", transcripción mostrada como mensaje de usuario con icono de micrófono.
- CLI: `tony voice warmup` (descarga y carga los modelos) y `tony voice bench` (p50/p95 de 5 repeticiones: carga, STT de 3 s, TTS de 12 palabras y, con `TONY_EVALS=1`, ida y vuelta completa); `tony doctor` comprueba el extra, `espeak-ng`, el alias de voz y la caché de modelos.
- Privacidad: el audio solo vive en memoria (nunca en disco ni en SQLite); los logs registran `stt.final {chars, duration_ms}` y `tts {sentences, duration_ms}`, nunca audio.

## Capabilities

### New Capabilities
- `voice-engines`: puertos `Vad`/`Stt`/`Tts` y sus contratos, adaptadores Silero/faster-whisper/Kokoro con carga única y ejecutor dedicado, dobles de prueba, extra `tony[voice]`, `tony voice warmup` y `tony voice bench`.
- `voice-input`: entrada de audio por WebSocket (`audio.start/chunk/end`), segmentación por VAD en el servidor, transcripción, `stt.final` procesado como `user.text`, límites (una intervención a la vez, `audio_not_started`, `voice_unavailable`) y privacidad del audio.
- `voice-output`: segmentador de frases, limpieza de markdown para voz, streaming `tts.start/chunk.meta/chunk/end`, cancelación `tts.cancelled`, degradación `tts_failed` y registro `tts {sentences, duration_ms}`.
- `web-ui-voice`: micrófono con captura `AudioWorklet` a 16 kHz, estados de escucha y transcripción, cola de reproducción a 24 kHz, captura silenciada durante la reproducción, botón "Detener audio", comportamiento por modo y micrófono deshabilitado sin el extra.

### Modified Capabilities
- `reply-mode`: la requirement "Precedencia del modo efectivo" añade que el `front` recibe `input_modality: voice|text` en el bloque dinámico del turno y que `set_reply_mode` por frase se refleja en el siguiente `user.accepted.effective_mode`.
- `ws-chat-protocol`: la requirement "Tipos de mensaje del cliente" deja de responder `not_implemented` a `audio.*` y admite frames binarios tras `audio.start`; nuevos tipos de servidor `stt.final`, `tts.*`.
- `web-server`: la requirement "Límite de tamaño de mensaje WebSocket" añade el límite de los frames binarios de audio (≤ 16 KiB por frame, 30 s por intervención); se añaden `voice` en `GET /api/health` y el cierre ordenado con síntesis en curso.
- `cli-doctor`: la requirement "Comprobaciones del entorno" amplía las comprobaciones de voz (extra instalado, `espeak-ng`, alias `voice.tts`/`voice.stt` válidos, modelos en caché) manteniéndolas informativas salvo el alias inválido, que es `✗`.

## Impact

- Código nuevo: `tony/core/voice/{ports,segmenter,cleanup,pipeline,executor}.py`, `tony/core/voice/engines/{silero,faster_whisper,kokoro}.py`, `tony/apps/web/{audio_ws,tts_stream}.py`, `tony/apps/cli/voice_cli.py`, `tony/apps/web/frontend/src/audio/{capture.worklet.ts,capture.ts,player.ts,level.ts}` y componentes `MicButton`/`StopAudioButton`/`VoiceStatus`; fixtures sintéticas en `tests/fixtures/audio/` y dobles en `tests/fakes/voice.py`.
- Código existente tocado de forma acotada: `tony/core/runner/front_prompt.py` (`input_modality` en el preámbulo), `tony/core/channels/session.py` (`handle` pasa la modalidad al preámbulo y acepta un `message_id` opcional para que `stt.final` y `user.accepted` compartan id), `tony/apps/web/{protocol,hub,server,ws_channel}.py` (tipos de audio, frames binarios, enganche del pipeline de voz), `tony/core/doctor/checks.py`, `tony/apps/cli/main.py` (`voice` sub-app), `pyproject.toml` (extra `voice`, marcador `voice`), `tests/test_architecture.py` (los motores reales solo se importan en `tony.core.voice.engines`), README.
- Dependencias: extra opcional `tony[voice]`; `espeak-ng` del sistema para Kokoro en español; modelos descargados a la caché estándar en el primer uso o con `tony voice warmup`. `uv run tony chat`, `tony run` y `tony web` sin el extra siguen funcionando.
- Pruebas: suite estándar sin motores reales ni red (`FakeVad`/`FakeStt`/`FakeTts`, WAV sintéticos); los motores reales solo con `uv run pytest -m voice` (excluido por defecto); Vitest para cola de reproducción y silenciado de captura.
- Depende de la entrega anterior (`tony web`, protocolo WS `v: 1`, `ConversationHub`, `WebChannel`, UI de chat) ya aplicada. Fuera de alcance: wake word, barge-in, modo offline sin modelo Claude, voz en CLI, clonación de voz, idiomas distintos de español/inglés.
