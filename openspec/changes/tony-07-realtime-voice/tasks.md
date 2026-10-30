# Tasks

Cada grupo sigue Rojo → Verde → Refactor: la prueba que falla se escribe y se ve fallar antes del código de producción. La suite estándar solo usa dobles (`FakeConversationRunner` con `speech_chunks`, `FakeVad`, `FakeStt`, `FakeTts`, `FakeClock`, `ListEventSink`, `ListSpeechSink`); los motores reales solo se prueban con el marcador `voice`. Referencias D1–D12: design.md.

## 1. Línea base y dependencias

- [x] 1.1 Antes de tocar código, con el código actual, ejecutar `TONY_EVALS=1 uv run tony voice bench` y guardar la salida en el scratchpad de la sesión como columna "antes"; verificar que contiene `load`, `stt_3s`, `tts_12w` y `roundtrip`
- [x] 1.2 Rojo: ampliar `tests/test_dependencies.py` para exigir `piper-tts>=1.8,<2` en el extra `voice`; verificar que falla
- [x] 1.3 Verde: añadir `piper-tts>=1.8,<2` al extra `voice` de `pyproject.toml`, `uv lock` y `uv sync --extra web --extra voice`; añadir `samples/voices/` a `.gitignore`; verificar que 1.2 pasa, que `uv run python -c "import piper"` funciona y que `git check-ignore samples/voices/x.wav` lo ignora

## 2. Configuración de voz (`tony.core.config`, spec `core-config`)

- [x] 2.1 Rojo: ampliar las pruebas de configuración: valores por defecto de `voice` exactamente como en el escenario "Fichero de configuración ausente"; rangos de `end_silence_ms` (299 ✗, 300 ✓, 1500 ✓, 1501 ✗), `barge_in_threshold` (0,49 ✗, 0,5 ✓, 0,99 ✓, 1,0 ✗), `barge_in_min_speech_ms` (149 ✗, 150 ✓, 1000 ✓, 1001 ✗), `cpu_threads` (`null` ✓, 0 ✗, 64 ✓, 65 ✗), `acknowledgements` (lista vacía ✗, 11 frases ✗, frase de 61 caracteres ✗, frase vacía ✗); cada error nombra la ruta `voice.<campo>`; verificar que falla
- [x] 2.2 Verde: ampliar `VoiceSettings` con los campos y validadores de D7; verificar que 2.1 y las pruebas de configuración existentes pasan
- [x] 2.3 Actualizar los comentarios de la sección `voice` en `config/tony.yaml` con los valores por defecto nuevos; verificar que `uv run tony config validate` pasa

## 3. Alias de voz con parámetros (`tony.core.voice.aliases`, specs `voice-engines`, `web-server`)

- [x] 3.1 Rojo: ampliar `tests/core/voice/test_aliases.py` con la tabla de D5: `kokoro/ef_dora` → `VoiceAlias("kokoro", (("ef_dora", 1.0),), speed=1.0, lang="es-419")`; `piper/es_MX-ald-medium?speed=0.95`; `kokoro/em_alex*0.6+em_santa*0.4?speed=0.94&lang=es`; errores en español que contienen el alias para: voz Piper fuera del catálogo (lista las válidas), `?pitch=2` (nombra `pitch`, `speed`, `lang`), `speed=0.49`/`1.51` (rango 0,5–1,5; 0,5 y 1,5 válidos), pesos 0,6+0,6 (deben sumar 1; 0,6+0,395 válido por tolerancia), `lang=fr`, `lang` en Piper, mezcla en Piper, clave repetida; `faster-whisper/base` válido; verificar que falla
- [x] 3.2 Verde: implementar `VoiceAlias`, el parseo y la validación, y adaptar `EngineRegistry` y `voice_availability` al nuevo parseo; verificar que 3.1 y las pruebas de `doctor`, `config validate` y alias existentes pasan
- [x] 3.3 Rojo/Verde: actualizar la prueba de `GET /api/health` al escenario "Voz disponible" (`stt: "faster-whisper/base"`, `tts: "kokoro/ef_dora"`) y comprobar que ningún modelo se carga; verificar que pasa

## 4. Detector con umbral y silencio de cierre (`tony.core.voice.{ports,utterances}`, `engines/silero.py`, spec `voice-engines`)

- [x] 4.1 Rojo: ampliar `tests/core/voice/test_utterances.py` y las pruebas de `FakeVad`: cierre con 500 ms por defecto (468 ms no cierra, 500 ms cierra); `end_silence_ms=700` con 600 ms no cierra; 1 s + 400 ms + 1 s no cierra; dos ventanas separadas por 10 de silencio se descartan; 200 ms de habla se descartan y 300 ms no; corte a 30 s; `classify(window, threshold)` con probabilidad 0,6 → habla con 0,5 y silencio con 0,8; `VadSegmenter.feed(pcm, threshold)` reenvía el umbral; verificar que falla
- [x] 4.2 Verde: cambiar el puerto `Vad.classify` para recibir `threshold`, `SileroVad` compara la probabilidad con ese umbral, `UtteranceAssembler` toma `end_silence_ms` de la configuración y `FakeVad` interpreta el umbral; verificar que 4.1 y toda la suite de voz con dobles pasan
- [x] 4.3 Rojo/Verde bajo marcador `voice`: `SileroVad` real sobre `tests/fixtures/audio/silence_1s.wav` no da habla con 0,5 ni con 0,8; verificar con `uv run pytest -m voice -k silero`

## 5. Motores: Piper, Kokoro configurable e hilos (`tony.core.voice.engines`, spec `voice-engines`)

- [x] 5.1 Rojo (sin motores reales, con factorías inyectadas): `EngineRegistry` construye `piper` o `kokoro` según el alias y una sola vez por alias completo; `cpu_threads` (o la mitad de los núcleos lógicos con `os.cpu_count` falso: 12 → 6, 1 → 1) llega a la factoría de STT y a la de Kokoro; `warmup` devuelve `{vad, stt, tts}`; `voice_availability` exige el módulo `piper` solo si el alias usa `piper`; verificar que falla
- [x] 5.2 Verde: implementar `engines/piper.py` (`PiperTts`: descarga con `hf_hub_download` desde `rhasspy/piper-voices`, `length_scale = 1/speed`, remuestreo FFT 22 050 → 24 000 Hz) y ampliar `engines/kokoro.py` (`g2p` sustituido por `EspeakG2P(language=lang)`, mezcla ponderada de tensores, `speed`, `torch.set_num_threads(cpu_threads)` en el hilo de síntesis) y `engines/faster_whisper.py` (`cpu_threads` configurable); verificar que 5.1 pasa
- [x] 5.3 Rojo/Verde bajo marcador `voice`: Piper `es_MX-ald-medium` sintetiza `Buenos días, señor.` a 24 kHz con duración dentro del 1 % de la original a 22 050 Hz, sin muestras en ±1,0, y remuestreo < 10 ms por frase; Kokoro `em_alex` con `es-419` fonemiza `cielo, zapato` sin `θ` y con `?lang=es` con `θ`; la mezcla 0,6/0,4 sintetiza audio no vacío; `faster-whisper/base` transcribe "¿qué hora es?" sintetizado con Piper y remuestreado a 16 kHz como texto que contiene `qué hora es`; verificar con `uv run pytest -m voice`
- [x] 5.4 Ejecutar `uv run tony voice warmup` y verificar que descarga la voz Piper y carga `vad`, `stt` (`base`) y `tts` (Piper) imprimiendo sus tiempos

## 6. Primer fragmento corto y pausas (`tony.core.voice.{segmenter,pipeline}`, spec `voice-output`)

- [x] 6.1 Rojo: ampliar `tests/core/voice/test_segmenter.py` con el modo `first_clause`: `Buenas tardes, señor. Los sistemas están en línea.` → [`Buenas tardes,`, `señor.`, `Los sistemas están en línea.`]; `La reunión de las cinco con el equipo sigue en pie.` → [`La reunión de las cinco con`, `el equipo sigue en pie.`]; `Cuesta 10,5 euros, señor.` → primera pieza `Cuesta 10,5 euros,`; coma en la 9.ª palabra → corte tras la 6.ª; `Sr. Pérez, …` no corta en `Sr.`; streaming palabra a palabra produce las mismas piezas; cada pieza lleva su tipo de corte (`clause`/`sentence`/`final`); la tabla de segmentación existente sigue igual con el modo desactivado; verificar que falla
- [x] 6.2 Rojo: ampliar `tests/core/voice/test_pipeline.py` con `FakeTts`: tras una pieza `sentence` el último fragmento termina con 160 ms de ceros (3 840 muestras a 24 kHz), tras `clause` con 80 ms y tras la última sin ceros añadidos; la redacción por frase sigue cubriendo un secreto partido entre fragmentos; `SpeechStats.duration_ms` incluye las pausas; verificar que falla
- [x] 6.3 Verde: implementar el modo `first_clause` y las pausas (D3, D4) y activarlo en `SpeechStreamer`; verificar que 6.1, 6.2 y las pruebas de `tts_stream` existentes pasan

## 7. Extractor de JSON parcial (`tony.core.runner`, spec `front-agent`)

- [x] 7.1 Rojo: escribir `tests/core/runner/test_partial_json.py` con partición de equivalencia y valores límite: trozos de 1 carácter y de todo el JSON dan el mismo resultado; `speech_text` antes y después de `display_text`; `speech_text: null`; escapes `\"`, `\\`, `\n`, `á` y un `\uXXXX` partido en 3 trozos; barra invertida al final de un trozo; claves desconocidas con objetos y listas anidados ignoradas; espacios entre tokens; JSON roto (`{"speech_text": 5`) → `broken` sin excepción y sin más emisiones; un *golden file* con la secuencia de emisiones del flujo grabado en la sonda (fichero bajo `tests/fixtures/`); verificar que falla
- [x] 7.2 Verde: implementar `PartialJsonFieldExtractor` sin dependencias (D1); verificar que 7.1 pasa

## 8. Runner del `front` en streaming y estilo de Jarvis (`tony.core.runner.{conversation,reply_mode}`, `agents/jarvis/agent.md`, spec `front-agent`)

- [x] 8.1 Rojo: ampliar las pruebas de `ClaudeSdkConversation` con un `SessionClient` falso que emite `StreamEvent` (`content_block_start` `tool_use` `StructuredOutput`, `input_json_delta`, `content_block_stop`) y un bloque previo `mcp__tony__delegate` con entrada parcial: `on_speech` y `on_text` reciben solo los fragmentos de `StructuredOutput` en orden; sin `StreamEvent` no se invocan y `FrontTurn` es igual al actual; JSON parcial roto no lanza; `build_front_options` fija `include_partial_messages=True` y `effort="low"`; `FrontReply.model_json_schema()["properties"]` empieza por `speech_text`; verificar que falla
- [x] 8.2 Verde: consumir `StreamEvent` en `_receive` con un extractor por bloque `StructuredOutput`, reordenar `FrontReply` y fijar las opciones (D1, D2); verificar que 8.1 y las pruebas de `front-agent`, `reply-mode` y `tts_stream` existentes pasan
- [x] 8.3 Rojo: prueba de agentes incluidos: `agents/jarvis/agent.md` carga con `style.voice` que contiene `señor`, `sereno` y `español latinoamericano neutro`, y el prompt del turno en modo `voice` contiene esa instrucción; verificar que falla
- [x] 8.4 Verde: reescribir `style.voice` y las líneas del cuerpo de `agents/jarvis/agent.md` sobre el estilo hablado según el brief (conciso, sereno, preciso, ironía sutil solo cuando encaje, "señor", sin exclamaciones ni entusiasmo, números redondeados dichos con naturalidad, vocabulario latinoamericano neutro sin regionalismos ni peninsularismos, identidad original); verificar que 8.3 pasa y que `uv run tony doctor --offline` no reporta `✗` del agente
- [x] 8.5 Con `TONY_EVALS=1`, ejecutar los evals de conversación del `front` con `effort="low"`; verificar que pasan igual que antes o, si no, volver al esfuerzo por defecto y actualizar el escenario "Opciones seguras del front" y D2 en este cambio

## 9. Turno interrumpible y aviso de delegación (`tony.core.channels.session`, spec `voice-input`)

- [x] 9.1 Rojo: ampliar `FakeConversationRunner` con un turno que se bloquea hasta `interrupt()` tras emitir `on_text("Son las")`, y ampliar `tests/core/channels/test_chat_session.py`: `interrupt_turn()` interrumpe el runner sin cancelar tareas; el turno interrumpido envía `AssistantReply` con `display_text == "Son las …"`, `speech_text is None`, sin `error`, y se persiste; sin texto previo → `(interrumpido)`; `interrupt()` existente sigue cancelando tareas; `delegate()` envía `DelegationStarted(reply_id)` antes de esperar la tarea; verificar que falla
- [x] 9.2 Verde: implementar `interrupt_turn()`, el cierre del turno interrumpido y el mensaje de canal `DelegationStarted` (D8, D10); verificar que 9.1 y las pruebas de `chat_session` existentes pasan

## 10. Protocolo e interrupción por voz en el servidor (`tony.apps.web.{protocol,audio_ws,hub}`, specs `ws-chat-protocol`, `voice-input`, `voice-output`)

- [x] 10.1 Rojo: ampliar `tests/apps/web/test_protocol.py`: `playback.stopped {message_id: "m-2"}` es un tipo válido sin respuesta, también con un `message_id` desconocido; `playback.stopped {}` y `{message_id: 5}` → `bad_payload`; `ping` sigue siendo `unknown_type`; verificar que falla
- [x] 10.2 Rojo: escribir `tests/apps/web/test_playback_window.py` con `FakeClock`: abierta en `tts.start`; cerrada por `playback.stopped`, por `tts.cancelled` y por tiempo tras primer chunk + suma de duraciones + 2 s (límite exacto: abierta 1 ms antes, cerrada en el instante); varios mensajes solapados; verificar que falla
- [x] 10.3 Rojo: ampliar `tests/apps/web/test_audio_ws.py` con `FakeVad`/`FakeStt` y una ventana falsa: mientras suena, umbral 0,8 (probabilidad 0,6 no abre intervención); 280 ms de habla estricta disparan `on_barge_in` una sola vez y 250 ms no; la intervención continúa y se transcribe tras 500 ms de silencio; `barge_in=False` descarta los frames sin clasificar ni error; verificar que falla
- [x] 10.4 Rojo: escribir `tests/apps/web/test_barge_in.py` sobre `build_test_app` con dobles: frames de habla mientras fluyen `tts.chunk` → `tts.cancelled` antes del cierre de la intervención, después `stt.final` y `user.accepted`; JSONL con `barge_in {message_id, speech_ms}` sin texto ni audio; turno aún generando → `assistant.final {display_text: "… …"}` sin `error turn_failed` y luego el turno nuevo sin `turn_in_progress`; turno esperando una tarea delegada → solo `tts.cancelled`, la tarea sigue `running` y la transcripción recibe `turn_in_progress`; eco (`las diez y media` tras cancelar `Son las diez y media, señor.`) → ni `stt.final` ni turno y JSONL con `barge_in.echo`; transcripción de 2 palabras contenida no se trata como eco; `cancel {message_id}` y `audio.start` siguen cancelando como antes; verificar que falla
- [x] 10.5 Verde: implementar `playback.stopped` en el protocolo, `PlaybackWindow`, el modo de escucha durante la reproducción en `AudioSession` y `Hub._on_barge_in`/filtro de eco/espera del turno interrumpido (D8, D9, D11); verificar que 10.1–10.4 y toda la suite de `tests/apps/web` pasan
- [x] 10.6 Documentar en el README (sección de voz) la interrupción por voz, `voice.barge_in*`, el filtro de eco, la limitación durante delegaciones y la recomendación de auriculares si el AEC falla; actualizar la línea de limitaciones que dice que no hay barge-in; verificar que los nombres de configuración documentados coinciden con `VoiceSettings`

## 11. Acuses pregrabados (`tony.apps.web.{tts_stream,ws_channel}`, spec `voice-output`)

- [x] 11.1 Rojo: escribir `tests/apps/web/test_ack_cache.py` y ampliar `test_tts_stream.py` con `FakeTts` y `FakeConversationRunner` que delega: con la caché lista, `DelegationStarted` en modo `voice` produce `tts.start` y el primer `tts.chunk` del acuse sin nueva llamada al `FakeTts` (contador) y antes del `speech_text`, con `seq` continuo en el mismo `message_id`; rotación en orden por las 3 frases; modo `text` → ningún `tts.*`; caché sin preparar → sin acuse ni espera; una respuesta que ya tiene audio no recibe acuse; la caché se sintetiza una vez por voz; verificar que falla
- [x] 11.2 Verde: implementar `AckCache` y `SpeechStreamer.acknowledge` (D10) y precalentar la caché al primer uso de voz; verificar que 11.1 pasa

## 12. Benchmark y paquete de voces (`tony.apps.cli.voice_cli`, `scripts/`, spec `voice-engines`)

- [x] 12.1 Rojo: ampliar `tests/apps/test_cli_voice.py` con un `EngineRegistry` falso y `FakeClock`: sin `TONY_EVALS` imprime p50/p95 de `load`, `stt_3s`, `stt_utt`, `tts_12w` y `tts_first` y no toca el runtime; con `TONY_EVALS=1` y dobles imprime además `roundtrip`, `ttft` y `roundtrip_stream` con el desglose `endpoint/stt/ttft/tts_first` y marca "objetivo no alcanzado" solo si p50 de `roundtrip_stream` > 2500 ms (2500 no marca, 2501 sí); verificar que falla
- [x] 12.2 Verde: implementar las medidas de D12 (`roundtrip_stream` con `AudioSession` y `ChatSession` reales, audio sintetizado con la voz por defecto y remuestreado a 16 kHz más silencio a ritmo real); verificar que 12.1 pasa
- [x] 12.3 Escribir `scripts/voice_samples.py`, que genera en `samples/voices/` un WAV por candidata de D6 con el párrafo de referencia ("Buenas tardes, señor. Los sistemas están en línea y la reunión de las cinco sigue en pie. Si me permite la sugerencia, quizá convenga revisar el informe antes; tiene un par de cifras optimistas.") e imprime una tabla Markdown (candidata, primer fragmento p50 ms, f0 aproximado, transcripción de vuelta exacta sí/no, notas); ejecutarlo con `uv run python scripts/voice_samples.py`; verificar que crea 7 WAV no rastreados por git
- [x] 12.4 Añadir al README la tabla de candidatas de 12.3, la voz elegida y por qué (D6), cómo cambiarla con `voice.tts` (sintaxis de alias con `speed`, `lang` y mezclas) y la licencia GPL de `piper-tts`; verificar que cada alias de ejemplo del README pasa `uv run tony config validate`

## 13. Frontend: captura abierta y parada inmediata (`tony/apps/web/frontend/src`, spec `web-ui-voice`)

- [x] 13.1 Rojo: ampliar `src/audio/capture.test.ts`, `src/audio/player.test.ts`, `src/protocol/reducer.test.ts` y `src/App.test.tsx`: `MIC_CONSTRAINTS` con `echoCancellation`, `noiseSuppression` y `autoGainControl` a `true`; frames enviados entre `tts.start` y `tts.end` (sustituye a "mutes the capture…"); `tts.cancelled` llama a `stop()` en todas las fuentes programadas y la amplitud vuelve a 0; un `tts.chunk` posterior del mismo `message_id` no se programa; exactamente un `playback.stopped {message_id}` al vaciarse la cola tras `tts.end`, al llegar `tts.cancelled` y al pulsar "Detener audio"; "Transcribiendo…" tras 500 ms sin nivel (499 ms no) y nunca mientras suena audio; verificar que falla
- [x] 13.2 Verde: retirar el silenciado ligado a `tts.*`, registrar las fuentes en `PcmPlayer`, enviar `playback.stopped` y ajustar el umbral de transcripción (D11); verificar que 13.1 y `npm test` completo pasan
- [x] 13.3 Refactor con las pruebas en verde (SRP en `App.tsx` y `hooks.ts`); verificar `npm test` y `npm run lint`

## 14. Mutación sobre el diff

- [x] 14.1 Ejecutar `mutmut` solo sobre los módulos Python modificados (`tony/core/runner/partial_json.py`, `tony/core/voice/{aliases,segmenter,utterances,pipeline}.py`, `tony/apps/web/{playback_window,audio_ws}.py` y el filtro de eco), abortando a los 3 min; verificar puntuación > 95 % o justificar cada mutante superviviente en el resumen de la tarea
- [x] 14.2 Ejecutar Stryker con `npx` solo sobre `src/audio/{player,capture}.ts` y `src/protocol/reducer.ts`, abortando a los 3 min; verificar > 95 % o justificar los supervivientes

## 15. Verificación final (integración)

- [x] 15.1 Ejecutar `uv run pytest -q`; verificar que pasa y que ninguna prueba estándar importa `faster_whisper`, `kokoro`, `piper` ni `silero_vad`
- [x] 15.2 Ejecutar `uv run pytest -m voice`; verificar que pasa con los modelos en caché
- [x] 15.3 Ejecutar `uv run ruff check . && uv run ruff format --check .`; verificar que no hay errores
- [x] 15.4 Ejecutar `npm test && npm run lint && npm run build` en `tony/apps/web/frontend`; verificar que los tres terminan sin errores
- [x] 15.5 Ejecutar `TONY_EVALS=1 uv run tony voice bench` y añadir al README la tabla antes/después (columna "antes" de 1.1) con `stt_3s`, `stt_utt`, `tts_12w`, `tts_first`, `ttft`, `roundtrip` y `roundtrip_stream` más el desglose; verificar que p50 de `roundtrip_stream` ≤ 2500 ms o que el README documenta la brecha con su desglose y las palancas siguientes de design.md
- [x] 15.6 Con el servidor en 127.0.0.1:8787 ya reiniciado por la sesión padre (estas tareas no lo reinician), ejecutar `scripts/ws_realtime_check.py`: sintetiza "¿qué hora es?" con Kokoro, lo remuestrea a 16 kHz, envía `hello`, `audio.start` y frames de 32 ms a ritmo real más 700 ms de silencio, y mide desde el último frame con habla hasta el primer binario de `tts.chunk`; verificar que imprime el tiempo y la secuencia `stt.final` → `user.accepted` → `tts.start` → `tts.chunk.meta` y que el primer `tts.chunk.meta` llega antes de `assistant.final` o, si no, explicar por qué
- [x] 15.7 Con el mismo servidor, ejecutar `scripts/ws_barge_in_check.py`: provoca una respuesta hablada larga y, mientras llegan `tts.chunk`, envía frames de una frase distinta sintetizada; verificar que llegan `tts.cancelled` del mensaje en curso y después un `stt.final` nuevo con su `user.accepted`
- [ ] 15.8 Prueba manual con altavoces (sin auriculares) en el navegador: 5 respuestas habladas sin hablar encima; verificar ≤ 1 autointerrupción (si no, aplicar la mitigación de design.md, Riesgos) y que hablar encima corta el audio y el orbe pasa a `listening`/`thinking`
  (pendiente: requiere altavoces/micrófono reales; no verificable desde este agente)
- [x] 15.9 Commits en la rama `feat/realtime-voice` con Conventional Commits atómicos por grupo (p. ej. `feat(voice): add piper engine and parametrized voice aliases`, `feat(voice): stream speech from partial front output`, `feat(voice): add barge-in detection and cancellation`, `feat(web-ui): keep mic open during playback`, `docs(voice): record realtime bench and voice candidates`), sin trailer `Co-Authored-By` ni atribución a IA; verificar con `git log --format=%B feat/realtime-voice ^main` que ningún mensaje contiene `Co-Authored-By`

## Workflow follow-up

- Elegir de oído la voz final con `samples/voices/` y, si cambia, ajustar `voice.tts` por defecto y la tabla del README.
- Archivar el cambio tras la revisión y sincronizar las specs principales.
