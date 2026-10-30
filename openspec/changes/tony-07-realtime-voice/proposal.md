# Proposal

## Why

La conversación por voz con Jarvis es por turnos y lenta: p50 ≈ 9,4 s desde que el usuario deja de hablar hasta el primer audio, porque el `front` espera la respuesta JSON completa, el STT `small` cuesta ~1,4 s y la primera frase de Kokoro ~3 s. Además, el micrófono se silencia mientras Tony habla, así que no se le puede interrumpir. El usuario pide hablar "en tiempo real" con interrupción natural y una voz con identidad propia: masculina, latinoamericana neutra (con seseo), serena y precisa, al estilo de un asistente cinematográfico.

## What Changes

- **Streaming LLM → TTS:** el `front` emite salida parcial (`include_partial_messages`); `speech_text` va primero en el contrato estructurado y se extrae de forma incremental del JSON parcial, se trocea en frases en cuanto se completan, se redacta frase a frase y se sintetiza al momento. `display_text` llega como `assistant.delta`. `assistant.final` no cambia. Si no hay salida parcial, se mantiene el comportamiento actual.
- **Primer fragmento corto y pausas naturales:** la primera pieza hablada se corta en la primera cláusula (coma o ≤ 6 palabras), las siguientes son frases completas, con silencios breves entre frases (~160 ms) y cláusulas (~80 ms).
- **Acuses pregrabados:** frases cortas ("Un momento, señor.") se sintetizan una vez y se reproducen al instante cuando el `front` delega una tarea.
- **Endpointing y STT más rápidos:** silencio de cierre configurable (por defecto 500 ms, antes 700 ms) manteniendo el mínimo de 300 ms de habla; STT por defecto `faster-whisper/base` (medido: ~0,9 s frente a ~3,5 s de `small`); hilos de CPU de los motores configurables.
- **Interrupción por voz (barge-in):** el micrófono sigue abierto durante la reproducción con cancelación de eco del navegador; durante la reproducción el detector usa un umbral más estricto y exige ~280 ms de habla. Al detectarla, el servidor cancela la síntesis (`tts.cancelled`), interrumpe el turno del `front` si aún genera y procesa la nueva intervención. Las tareas delegadas no se cancelan. Las transcripciones que repiten lo que Tony estaba diciendo (eco) se descartan.
- **Nueva voz por defecto:** motor Piper (`es_MX-ald-medium`, masculina, fonemas `es-419` con seseo, ~0,1–0,3 s por frase en CPU) detrás del puerto `Tts` existente; Kokoro sigue disponible con voces masculinas, mezclas de voces y fonemizador `es-419`. El alias `voice.tts` admite parámetros (`?speed=…&lang=…`) y es compatible con `kokoro/ef_dora`. Un paquete de muestras WAV permite elegir de oído.
- **Persona hablada:** `agents/jarvis/agent.md` actualiza `style.voice` y el prompt al estilo pedido: conciso, sereno, preciso, ironía sutil, "señor", español neutro latinoamericano sin regionalismos.
- **Protocolo:** nuevo mensaje de cliente `playback.stopped {message_id}` para que el servidor sepa cuándo dejó de sonar el audio. No hay mensajes nuevos del servidor.
- **Medición:** `tony voice bench` añade el tiempo hasta el primer token del `front` y la ida y vuelta en streaming (fin del habla → primer `tts.chunk`), con desglose; el README recoge la tabla antes/después. Objetivo: p50 ≤ 2,5 s sin tools, o la brecha documentada con su desglose.
- **BREAKING** (configuración por defecto): `voice.stt` pasa a `faster-whisper/base` y `voice.tts` a `piper/es_MX-ald-medium?speed=0.95`; quien quiera lo anterior lo fija en `config/tony.yaml`. El extra `voice` añade `piper-tts`.
- Fuera de alcance: wake word, modelos speech-to-speech full-duplex, cambiar de proveedor de LLM y transcripciones parciales (`stt.partial`).

## Capabilities

### New Capabilities
- (ninguna)

### Modified Capabilities
- `voice-engines`: umbral del detector y silencio de cierre configurables, alias de síntesis con parámetros (velocidad, idioma del fonemizador, mezcla de voces), motor Piper, voz por defecto, hilos de CPU, STT `base` por defecto, extra con `piper-tts` y métricas nuevas del benchmark.
- `voice-input`: endpointing configurable y detección de interrupción por voz durante la reproducción, turno interrumpido, descarte de eco y desactivación del barge-in.
- `voice-output`: primer fragmento corto, pausas naturales, acuses pregrabados para delegaciones y cancelación por interrupción de voz.
- `front-agent`: salida parcial en streaming con `speech_text` primero y esfuerzo bajo, extracción incremental y estilo hablado de Jarvis.
- `ws-chat-protocol`: tipo de cliente `playback.stopped` y su validación.
- `web-ui-voice`: captura abierta durante la reproducción con cancelación de eco, parada local inmediata, aviso `playback.stopped` y umbral de "Transcribiendo…" alineado.
- `core-config`: valores por defecto nuevos de la sección `voice`.
- `web-server`: el ejemplo de salud refleja el STT por defecto nuevo.

## Impact

- Backend: `tony/core/runner/conversation.py` y `reply_mode.py` (opciones, orden del esquema, consumo de `StreamEvent`), nuevo extractor incremental en `tony/core/runner/`, `tony/core/voice/` (`ports.py`, `utterances.py`, `segmenter.py`, `pipeline.py`, `aliases.py`, `engines/` con un adaptador Piper nuevo y cambios en Kokoro, Silero y faster-whisper), `tony/core/config/settings.py`, `tony/core/channels/session.py` (interrupción del turno sin cancelar tareas), `tony/apps/web/` (`hub.py`, `audio_ws.py`, `tts_stream.py`, `protocol.py`) y `tony/apps/cli/voice_cli.py`.
- Frontend: `src/audio/capture.ts`, `src/audio/hooks.ts`, `src/audio/player.ts`, `src/App.tsx`, `src/protocol/reducer.ts` y sus pruebas.
- Datos: `agents/jarvis/agent.md`, `config/tony.yaml` (comentarios de valores por defecto), `README.md` y `.gitignore` (`samples/voices/`).
- Dependencias: `piper-tts` (GPL-3.0-or-later, CPU, `onnxruntime` ya presente) en el extra `voice`; voces Piper descargadas a la caché de Hugging Face. Sin dependencias nuevas en el frontend.
- Riesgos: autointerrupción por eco si la cancelación de eco del navegador falla; licencia GPL de `piper-tts`; p50 objetivo ajustado en esta CPU (estimación 2,6–3,0 s, ver design.md).
