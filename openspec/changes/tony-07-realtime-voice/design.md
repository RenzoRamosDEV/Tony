# Design

## Context

Motivación: ver proposal.md (Why). Estado actual relevante:

- `ClaudeSdkConversation` (`tony/core/runner/conversation.py`) usa `include_partial_messages=False` y `output_format` con `FrontReply {display_text, speech_text}`; `on_text`/`on_speech` existen en el puerto `ConversationRunner` pero nunca se invocan. `ChatSession.handle` ya los conecta a `AssistantDelta`/`AssistantSpeechDelta`, y `SpeechStreamer.on_delta` ya alimenta un `SpeechPipeline` por respuesta. La tubería streaming → TTS existe; falta la fuente.
- `SpeechPipeline` sintetiza frase a frase con `SentenceSegmenter`, redacta por frase (`spoken_mask`) y serializa el motor en el carril `tts` del `VoiceExecutor` (2 hilos).
- `UtteranceAssembler`: `END_SILENCE_MS=700`, `MIN_SPEECH_MS=300` y ventanas de 32 ms; `SileroVad.classify` usa un umbral fijo de 0,5.
- `ChatSession.interrupt()` cancela **todas** las tareas delegadas y luego interrumpe el runner. Si el runner se interrumpe mientras espera a `delegate`, `_settle_interrupted` cancela la tarea (`front_interrupted`).
- El cliente (`audio/capture.ts`) ya pide AEC/NS/AGC, pero `App.tsx` silencia la captura desde `tts.start` hasta que la cola se vacía (`playback_drained`).
- `tests/fakes/conversation.py::FakeConversationRunner` ya soporta `speech_chunks`; `tests/fakes/voice.py` tiene `FakeVad`/`FakeStt`/`FakeTts`; `tests/fakes/clock.py` tiene `FakeClock`.

### Mediciones de partida (sondas de solo lectura, Ryzen 5 7535U, 6 núcleos/12 hilos, sin GPU)

| Sonda | Resultado |
|---|---|
| Agent SDK 0.2.174, Haiku 5.5, `include_partial_messages=True` + `output_format` | La salida estructurada llega como `tool_use` llamado `StructuredOutput` con eventos `input_json_delta`; se respeta el orden de propiedades del esquema (`speech_text` primero en 2/2). Primer delta: 3,50 s en el primer turno (conexión en frío + bloque `thinking`) y 1,18 s en caliente; turno completo 4,25 s / 1,70 s. |
| Kokoro `ef_dora` con hilos por defecto (12) | Primer fragmento de 4 palabras 1 478 ms, 6 palabras 1 893 ms, 12 palabras 3 332 ms (Kokoro entrega un fragmento por frase: primer fragmento = frase entera). |
| Kokoro con `torch.set_num_threads(6)` / `(4)` | 4 palabras 857 / 1 080 ms; 12 palabras 2 059 / 2 571 ms. Con 6 hilos baja ~40 %. |
| faster-whisper `base` vs `small` (int8, CPU) | "¿qué hora es?" (1,1 s): 893 vs 3 962 ms; frase de 3,5 s: 1 074 vs 3 477 ms; 6 s: 1 801 ms (`base`). `small` alucina sobre los WAV sintéticos sin voz ("Subtítulos por la comunidad de Amara.org"); `base` devuelve vacío. `base` con 4 → 6 hilos: 980 → 902 ms. `tiny`: 5 725 ms sobre 6 s (bucles de decodificación) → descartado. |
| Kokoro voces masculinas, `es-419`, `speed=0.94` (6 hilos, con STT cargado) | `em_alex` 1 175 / 2 737 ms (4/12 palabras), f0 ≈ 133 Hz; `em_santa` 1 190 / 2 692 ms, f0 ≈ 142 Hz; mezcla 0,6/0,4 1 188 / 2 803 ms, f0 ≈ 127 Hz, la única transcripción de vuelta exacta del párrafo de referencia. `ef_dora` (`es`): 1 056 / 2 751 ms, f0 ≈ 168 Hz. |
| Fonemizador | `lang_code="e"` de Kokoro → `EspeakG2P(language="es")`: `cielo` → `θjˈelo`. Con `EspeakG2P(language="es-419")`: `sjˈelo`, `sapˈato`, `asˈeɾ`, `sˈinko`. |
| Piper 1.8.0 (`piper-tts`, onnxruntime CPU) | `es_MX-ald-medium`: 158 / 301 ms (4/12 palabras) con `length_scale=1.0` y 128 / 218 ms con 1,06; f0 ≈ 150 Hz (masculina); fonemas `es-419` (seseo); transcripción de vuelta exacta. `es_MX-claude-high`: 98 / 299 ms, f0 ≈ 185 Hz (tono más agudo), transcripción de vuelta con errores ("siriempie", "convenda"). Catálogo español de Piper: `es_AR-daniela-high` (femenina), `es_ES-*` (peninsulares), `es_MX-ald-{medium,x_low}` y `es_MX-claude-high`. Audio a 22 050 Hz. |

## Goals / Non-Goals

**Goals:**
- Reducir el tiempo hasta el primer audio sin tocar el contrato de `assistant.final`, reutilizando el camino existente `on_speech → SpeechStreamer → SpeechPipeline`.
- Interrupción por voz con detección en el servidor, sin dependencias nuevas en el navegador.
- Mantener los motores detrás de los puertos `Vad`/`Stt`/`Tts` existentes (Ports and Adapters): Piper es un adaptador más.

**Non-Goals:**
- VAD o detección de interrupción en el navegador; `stt.partial`; STT especulativo (ver Riesgos); cancelar tareas delegadas por voz (solo con `cancel {task_id}` o la UI); procesamiento de tono (pitch shifting).

## Decisions

### D1. Extracción incremental de `speech_text` desde `StructuredOutput`
- Activar `include_partial_messages=True` y reordenar `FrontReply` a `speech_text, display_text` (Pydantic conserva el orden de declaración en el esquema JSON; la sonda confirma que el modelo lo respeta).
- Nuevo componente puro `PartialJsonFieldExtractor` (en `tony/core/runner/`): recibe trozos de `partial_json`, sigue el estado léxico del objeto de primer nivel (clave/valor, dentro de cadena, escape pendiente, `\uXXXX` partido) y emite `(field, fragment)` para `speech_text` y `display_text`. Ante un estado inválido pasa a `broken` y deja de emitir (la respuesta final manda). Sin dependencias.
- El runner abre un extractor por bloque cuyo `content_block_start` es un `tool_use` con nombre `StructuredOutput` y lo cierra en `content_block_stop`; los bloques de otras tools (`mcp__tony__delegate`) se ignoran.
- `on_speech` → `AssistantSpeechDelta` → `SpeechStreamer.on_delta` (ya existe); `on_text` → `assistant.delta` (ya existe).
- Alternativas: (a) pedir texto libre con marcadores en vez de JSON: rompe la salida estructurada y la validación; (b) usar un parser JSON tolerante de terceros: dependencia nueva para ~80 líneas puras y fáciles de probar; (c) segunda llamada solo para hablar: duplica coste y latencia.
- Respaldo: sin `StreamEvent` (otra versión del SDK, motor de prueba) no hay deltas y `SpeechStreamer.start` habla el texto completo como hoy (front-agent "Respuesta final autoritativa sin parciales").
- Si el `speech_text` final difiere del emitido en streaming (no debería), el audio ya enviado no se rehace; `assistant.final` es autoritativo para el texto.

### D2. Esfuerzo `low` para el `front`
- `effort="low"` en las opciones del `front` (campo `effort` de `ClaudeAgentOptions`). La sonda muestra un bloque `thinking` antes de la salida en el primer turno. La guía de Claude para chat y rutas sensibles a latencia recomienda `low`. El `worker` no cambia.
- Puerta de calidad: los evals de conversación (`evals/conversaciones.yaml`) deben seguir pasando; si no, se vuelve al esfuerzo por defecto, se documenta y se corrige el escenario de front-agent en este mismo cambio.

### D3. Segmentación con primer fragmento corto
- `SentenceSegmenter` recibe un modo `first_clause`: mientras no haya emitido nada, corta en `,`/`:`/`;` seguidos de espacio dentro de las primeras 8 palabras, o tras la 6.ª palabra completa (palabra seguida de espacio). Después aplica las reglas de frase existentes. La coma decimal (`10,5`) no corta porque exige espacio después.
- Cada pieza lleva su tipo de corte (`clause` | `sentence` | `final`) para que el pipeline añada la pausa (D4).
- Con Piper la ganancia es pequeña (4 frente a 12 palabras ≈ 130 frente a 220 ms), pero es decisiva con Kokoro (≈ 1,1 frente a 2,7 s) y sigue siendo barata.

### D4. Pausas naturales en el pipeline
- `SpeechPipeline` añade ceros PCM al último fragmento de cada pieza: 160 ms tras `sentence`, 80 ms tras `clause` y nada tras la última. Es determinista y se prueba con `FakeTts`. No se usa `sentence_silence` de Piper para que el comportamiento sea igual con cualquier motor.

### D5. Alias de voz con parámetros (en lugar de un bloque estructurado)
- Gramática: `motor/voz[?clave=valor(&clave=valor)*]`; voz Kokoro = `id` o mezcla `id*peso(+id*peso)+`; claves `speed` (0,5–1,5) y `lang` (`es-419` | `es`, solo Kokoro). Ejemplos: `piper/es_MX-ald-medium?speed=0.95`, `kokoro/em_alex*0.6+em_santa*0.4?speed=0.94`.
- Por qué: una sola línea en YAML, el alias completo aparece tal cual en `/api/health`, `tony doctor` y los errores, y `kokoro/ef_dora` sigue siendo válido sin migración. Un bloque `voice.tts: {engine, voice, speed, …}` exigiría una unión de tipos en `VoiceSettings` y tocar salud y doctor.
- `aliases.parse_alias` devuelve un `VoiceAlias(engine, voices: tuple[(id, weight)], speed, lang)` inmutable y `validate_voice_settings` reutiliza ese parseo.
- Kokoro: la mezcla es la suma ponderada de los tensores de voz (`KPipeline.load_voice` por id); `speed` va al pipeline; para `lang` se sustituye `pipeline.g2p` por `misaki.espeak.EspeakG2P(language=lang)` tras construir `KPipeline(lang_code="e")`, porque Kokoro fija `es` (peninsular) para `lang_code="e"`. Por defecto es `es-419`; `ef_dora` cambia de pronunciación y `?lang=es` restaura la anterior.
- Piper: `speed` → `length_scale = 1 / speed`.

### D6. Motor Piper y voz por defecto
- Adaptador `PiperTts` (`tony/core/voice/engines/piper.py`) detrás de `Tts`. Carga `PiperVoice.load(model_path)` con el `.onnx` y su `.onnx.json` descargados con `huggingface_hub.hf_hub_download("rhasspy/piper-voices", "es/es_MX/ald/medium/es_MX-ald-medium.onnx")` a la caché estándar (`huggingface_hub` ya llega con Kokoro). Remuestrea 22 050 → 24 000 Hz con numpy (interpolación por FFT sobre el fragmento de la frase), sin dependencias nuevas; coste objetivo < 10 ms por frase, verificado en tareas.
- Catálogo de voces válido estático (las 9 voces `es_*` del índice de Piper), así la validación no necesita red.
- **Voz por defecto: `piper/es_MX-ald-medium?speed=0.95`.** Criterios del brief, en orden: masculina (f0 ≈ 150 Hz), seseo nativo (`es-419`, dataset mexicano), transcripción de vuelta exacta y primer fragmento ≈ 130–160 ms (Kokoro: ≈ 1,1–1,2 s, más de un tercio del presupuesto de 2,5 s). `speed=0.95` da el ritmo "calmado y preciso, nunca lento".
- Alternativa documentada para quien prime timbre grave sobre latencia: `kokoro/em_alex*0.6+em_santa*0.4?speed=0.94` (f0 ≈ 127 Hz, la más grave), a costa de ~1 s más hasta el primer audio. `es_MX-claude-high` se descarta por tono más agudo y peor inteligibilidad medida.
- Paquete de escucha: `scripts/voice_samples.py` (fuera del paquete `tony`) sintetiza el párrafo de referencia con cada candidata en `samples/voices/<candidata>.wav` (en `.gitignore`) e imprime la tabla para el README. Candidatas: `piper/es_MX-ald-medium` (speed 1,0 y 0,95), `piper/es_MX-claude-high`, `kokoro/em_alex`, `kokoro/em_santa`, mezcla 0,6/0,4 (las Kokoro con `es-419` y 0,94) y `kokoro/ef_dora` como referencia.
- Tono: no se aplica ningún procesado. `librosa` no está instalado, un vocoder de fase propio añade artefactos, y la mezcla de Kokoro ya ofrece un timbre más grave sin coste.

### D7. Endpointing, STT e hilos
- `VoiceSettings` añade `end_silence_ms=500`, `barge_in=True`, `barge_in_threshold=0.8`, `barge_in_min_speech_ms=280`, `cpu_threads=None` (→ `max(1, os.cpu_count() // 2)`, 6 en esta máquina) y `acknowledgements=[…]`. `stt` pasa a `faster-whisper/base`.
- `UtteranceAssembler(end_silence_ms=settings.end_silence_ms)`. `MIN_SPEECH_MS` sigue en 300.
- `cpu_threads` → `WhisperModel(cpu_threads=…)` y `torch.set_num_threads(…)` dentro del hilo del carril `tts` antes de sintetizar con Kokoro (Piper usa onnxruntime con su propia configuración y no se toca).
- 500 ms en lugar de 400 ms: las pausas internas habituales del habla rondan 250–450 ms, y bajar más cortaría frases ("Recuérdame… llamar a mamá").

### D8. Interrupción por voz en el servidor
- Puerto `Vad`: `classify(window, threshold) -> bool` (Silero compara la probabilidad con el umbral recibido; `FakeVad` usa la energía con umbral). `VadSegmenter.feed(pcm, threshold)`.
- `PlaybackWindow` (en `tony/apps/web/`, con `Clock` inyectado): se abre en `tts.start`, suma la duración de cada `tts.chunk` enviado y se cierra con `playback.stopped`, `tts.cancelled` o `max(fin estimado) + 2 s`. `AudioSession` consulta `speaking()` en cada ventana.
- Mientras `speaking()`: si `barge_in=False`, los frames se descartan antes de la VAD; si es `True`, se clasifica con `barge_in_threshold` y el ensamblador cuenta la habla de la intervención abierta; al alcanzar `barge_in_min_speech_ms` dispara `on_barge_in` una vez por intervención. La intervención sigue ensamblándose (con umbral normal en cuanto la ventana se cierra) y se transcribe como cualquier otra.
- `Hub._on_barge_in`: registra `barge_in`, guarda el texto hablado de las respuestas canceladas (para D9), llama a `speech.cancel_all()` (emite `tts.cancelled`) y, si `turn_in_progress` y `not session.has_active_task`, llama a `ChatSession.interrupt_turn()`.
- `ChatSession.interrupt_turn()` (nuevo; `interrupt()` no cambia): marca el turno como interrumpido y llama solo a `runner.interrupt()`. Al volver `turn()`, si está marcado: `display_text` = texto de `display_text` recibido por `on_text` + ` …` (o `(interrumpido)`), `speech_text=None` y sin `error`. Se persiste y se publica `assistant.final`. El `ResultMessage` de error que pueda devolver el SDK tras `interrupt` se ignora en ese caso.
- `Hub._on_transcript`: si hay un turno marcado como interrumpido por voz, espera a `self.turn` con un límite de 3 s antes de `user_text`; si el límite vence, se aplica la regla `turn_in_progress` existente.
- Con una tarea delegada activa no se interrumpe el `front`: interrumpirlo cancelaría la tarea (ver Context). Solo se corta el audio (normalmente el acuse) y la nueva transcripción recibe `turn_in_progress`.

```
cliente                  Hub/AudioSession            SpeechStreamer        ChatSession/runner
  │ frames (mic abierto) ──▶ VAD umbral 0,8                │                       │
  │                        ≥280 ms habla ─ on_barge_in ───▶ cancel_all ──▶ tts.cancelled ─▶ cliente para
  │                          │                             │        interrupt_turn() ─▶ runner.interrupt()
  │                        silencio 500 ms → STT base      │        assistant.final "… …"
  │ ◀── stt.final, user.accepted (tras asentarse el turno) ─────────────▶ turno nuevo (streaming)
```

### D9. Eco
- Primera línea: AEC/NS/AGC del navegador (ya pedidos). Segunda: umbral 0,8 y 280 ms. Tercera: filtro de eco en el servidor. Si la transcripción de una intervención que disparó un barge-in, normalizada, tiene ≥ 3 palabras y es subcadena del texto hablado cancelado (normalizado igual), se descarta con `barge_in.echo`. Esto evita bucles en los que Tony se responde a sí mismo. El audio cortado no se reanuda: reanudarlo exigiría retener la cancelación hasta transcribir, lo que anula la inmediatez.

### D10. Acuses pregrabados
- `AckCache` (en `tony/apps/web/`): al primer uso de voz (o en `warmup`) sintetiza en segundo plano cada frase de `voice.acknowledgements` con la voz configurada, por el carril `tts`, y guarda los `AudioChunk` en memoria (pocos KB). Nunca toca disco.
- Disparo: `ChatSession.delegate` publica un evento de canal `DelegationStarted(reply_id)` (nuevo `ChannelMessage`, sin tipo de protocolo nuevo). El `WebSocketChannel` lo pasa a `SpeechStreamer.acknowledge(reply_id)`, que, si el modo es hablado, la caché está lista y la respuesta no tiene audio aún, encola los fragmentos del acuse como primera pieza (pausa de `sentence`) del pipeline de esa respuesta. El `speech_text` posterior sigue en el mismo `message_id` y `seq`.
- `assistant.wait` (texto a los 3 s) no cambia.

### D11. Protocolo y cliente
- Único tipo nuevo: `playback.stopped {message_id}` del cliente, sin respuesta. No hay tipo `barge_in` del servidor: `tts.cancelled` ya basta para que el cliente pare, y el orbe pasa a `listening`/`thinking` por su prioridad existente.
- Cliente: se elimina `setMuted` ligado a `tts.*`; `AudioPlayer` guarda las fuentes programadas para llamar a `stop()` en todas al cancelar; envía `playback.stopped` una vez por `message_id` al vaciarse la cola tras `tts.end` o al parar; descarta `tts.chunk` de mensajes ya parados; el umbral de "Transcribiendo…" baja a 500 ms y solo cuenta sin audio de respuesta sonando.

### D12. Medición
- `tony voice bench` añade `stt_utt` (STT de "¿qué hora es?" sintetizado con la voz por defecto y remuestreado a 16 kHz), `tts_first` (primer fragmento de "Un momento, señor."), `ttft` (de `query` al primer `on_speech`) y `roundtrip_stream`: alimenta un `AudioSession` real con el audio sintetizado más silencio a ritmo de tiempo real, con un `ChatSession` real y un `SpeechStreamer` con sumidero de primer fragmento. Mide desde la última ventana con habla hasta el primer `tts.chunk` e imprime el desglose `endpoint`/`stt`/`ttft`/`tts_first`. Se mantiene `roundtrip` como referencia.
- Comprobaciones scriptadas de extremo a extremo por WebSocket (`scripts/ws_realtime_check.py` y `scripts/ws_barge_in_check.py`) contra el servidor en 127.0.0.1:8787, ya reiniciado por la sesión padre.

### Presupuesto estimado (sin tools, p50, voz por defecto)

| Etapa | ms | Fuente |
|---|---|---|
| Silencio de cierre | 500 | configuración |
| STT `base` (~1–1,5 s de habla) | 900 | sonda |
| Primer token útil del `front` (en caliente) | 1 200 | sonda (sin `effort=low`) |
| Hasta cerrar la primera cláusula | 50–150 | sonda: ~20 ms por delta |
| Primer fragmento Piper (4 palabras) | 130–160 | sonda |
| Entrega WS + programación en el cliente | < 30 | loopback |
| **Total** | **≈ 2 800–2 950** | |

Brecha esperada ≈ 0,3–0,45 s sobre 2,5 s. `effort=low` es la única palanca de este cambio que puede cerrarla. La alternativa es documentar la brecha con el desglose del bench (lo permite el criterio de aceptación). Palancas siguientes, fuera de alcance: STT especulativo al llegar a ~250 ms de silencio (−250 ms) y `end_silence_ms` 400.

## Risks / Trade-offs

- [El AEC del navegador no cubre la salida de Web Audio en Linux/PipeWire y Tony se interrumpe a sí mismo] → umbral 0,8 + 280 ms + filtro de eco D9 + `voice.barge_in: false`. Una tarea manual con altavoces mide las falsas interrupciones; con > 1 por cada 5 respuestas se documenta el uso de auriculares y se sube el umbral por defecto.
- [Interrupción a mitad de turno deja la sesión del SDK en un estado raro] → `interrupt()` del SDK ya se usa al cerrar. Las pruebas con `FakeConversationRunner` cubren el flujo y la comprobación scriptada de barge-in lo ejercita con el modelo real. Si el siguiente turno falla, el runner ya reabre con `resume` (`_reopen`).
- [Usuario que habla durante una delegación recibe `turn_in_progress`] → limitación aceptada y documentada en el README. Cancelar sigue disponible por la UI (`cancel {task_id}`).
- [Licencia GPL-3.0-or-later de `piper-tts` (piper1-gpl)] → Tony es de uso personal y local y la dependencia es opcional (extra `voice`). Si se distribuye, se cambia a `kokoro/…` por configuración sin tocar código. Las voces `es_MX-ald` (dataset Unlicense) y `es_MX-claude` (Apache-2.0) tienen licencias permisivas.
- [El modelo no respeta el orden `speech_text` primero] → el extractor emite cada campo en cuanto aparece, en cualquier orden. Si `display_text` va primero solo se pierde latencia, no corrección.
- [Remuestreo 22 050 → 24 000 con artefactos] → interpolación por FFT por frase. La prueba `voice` verifica duración y ausencia de clipping; la escucha del paquete de muestras confirma.
- [Más hilos de CPU (6 + 6) compitiendo entre STT y TTS durante un barge-in] → el carril serial de cada motor sigue igual; la contención se mide en `roundtrip_stream`.
- [`effort=low` degrada el criterio de delegación] → puerta con los evals (D2).

## Migration Plan

1. Valores por defecto nuevos (BREAKING menor): quien quiera lo anterior fija `voice.stt: faster-whisper/small` y `voice.tts: kokoro/ef_dora?lang=es` en `config/tony.yaml`.
2. `uv sync --extra web --extra voice` instala `piper-tts`; `uv run tony voice warmup` descarga la voz Piper a la caché de Hugging Face.
3. El cliente nuevo y el servidor se despliegan juntos (mismo repositorio). Un cliente antiguo seguiría silenciando la captura y no enviaría `playback.stopped`; el servidor cierra la ventana por tiempo (D8).
4. Marcha atrás: revertir los commits de la rama `feat/realtime-voice`. La configuración del usuario sigue siendo compatible hacia atrás.

## Open Questions

- Ajuste fino de `speed` (0,93–0,97) y elección final entre Piper `ald` y la mezcla de Kokoro por timbre: lo decide el usuario de oído con `samples/voices/`. Cambiarlo es solo configuración.
