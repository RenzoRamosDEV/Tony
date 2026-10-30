## MODIFIED Requirements

### Requirement: Puerto de detección de actividad de voz
El detector de voz SHALL recibir audio PCM Float32 a 16 kHz mono en fragmentos y devolver cero o más intervenciones completas por llamada, manteniendo estado por sesión y clasificando cada ventana con el umbral de habla vigente (0,5 por defecto). Una intervención SHALL terminar tras ≥ `voice.end_silence_ms` de silencio después de habla (500 ms por defecto); los tramos con < 300 ms de habla SHALL descartarse; una intervención SHALL cortarse a los 30 s.

#### Scenario: Silencio cierra la intervención
- **GIVEN** un detector nuevo con el silencio de cierre por defecto que recibe 1,5 s de habla seguidos de 500 ms de silencio
- **WHEN** se alimenta el último fragmento de silencio
- **THEN** devuelve exactamente una intervención con ~1,5 s de audio y su estado queda vacío

#### Scenario: Habla demasiado corta se descarta
- **GIVEN** 200 ms de habla seguidos de 1 s de silencio
- **WHEN** se alimentan los fragmentos
- **THEN** no se devuelve ninguna intervención

#### Scenario: Corte forzado a 30 s
- **GIVEN** 31 s de habla continua sin silencio
- **WHEN** se alimenta el fragmento que completa los 30 s
- **THEN** devuelve una intervención de 30 s y el segundo restante inicia una intervención nueva

#### Scenario: Habla breve separada por silencios
- **GIVEN** dos ventanas de habla separadas por 10 ventanas de silencio (64 ms de habla)
- **WHEN** se cierra la intervención
- **THEN** se descarta aunque dure más de 300 ms

#### Scenario: Silencio insuficiente no cierra
- **GIVEN** 1 s de habla, 400 ms de silencio y 1 s de habla
- **WHEN** se alimentan los fragmentos
- **THEN** no se devuelve ninguna intervención hasta que lleguen ≥ 500 ms de silencio

#### Scenario: Silencio de cierre configurado
- **GIVEN** `voice.end_silence_ms: 700`
- **WHEN** llegan 1 s de habla y 600 ms de silencio
- **THEN** no se devuelve ninguna intervención hasta completar 700 ms de silencio

#### Scenario: Umbral más estricto
- **GIVEN** una ventana con probabilidad de habla 0,6
- **WHEN** se clasifica con umbral 0,5 y con umbral 0,8
- **THEN** cuenta como habla con 0,5 y como silencio con 0,8

### Requirement: Puerto de síntesis
El sintetizador SHALL recibir un texto y devolver un flujo de fragmentos PCM Int16 a 24 kHz mono, remuestreando si el motor trabaja a otra frecuencia. La voz SHALL tomarse de `voice.tts` con el formato `motor/voz[?param=valor&…]` (por defecto `piper/es_MX-ald-medium?speed=0.95`); `kokoro/ef_dora` sigue siendo válido. Un alias con motor, voz o parámetro inexistente SHALL fallar al cargar con un mensaje en español que nombre el alias.

#### Scenario: Flujo de fragmentos
- **WHEN** se sintetiza `Buenos días, señor.` con la voz por defecto
- **THEN** se obtienen uno o más fragmentos PCM Int16 a 24 kHz mono cuya duración total es mayor que 0

#### Scenario: Alias inválido
- **GIVEN** `voice.tts: kokoro/no_existe`
- **WHEN** se carga el motor de síntesis
- **THEN** falla con un mensaje en español que contiene `kokoro/no_existe`

#### Scenario: Parámetro desconocido
- **GIVEN** `voice.tts: piper/es_MX-ald-medium?pitch=2`
- **WHEN** se valida la configuración
- **THEN** falla con un mensaje en español que nombra `pitch` y los parámetros admitidos (`speed`, `lang`)

#### Scenario: Alias antiguo sin parámetros
- **GIVEN** `voice.tts: kokoro/ef_dora`
- **WHEN** se carga el motor
- **THEN** carga sin error con velocidad 1,0 y fonemizador `es-419`

### Requirement: Motores locales y dobles de prueba
El sistema SHALL ofrecer motores locales Silero (detección), faster-whisper en CPU `int8` con modelo `base` por defecto (transcripción), Piper y Kokoro (síntesis), y dobles para pruebas: detección por umbral de energía, transcripción con texto fijado y síntesis senoidal. Los hilos de CPU de los motores SHALL fijarse con `voice.cpu_threads` (por defecto la mitad de los núcleos lógicos). La suite estándar SHALL usar solo los dobles; los motores reales, solo con el marcador `voice`.

#### Scenario: Suite estándar sin motores
- **GIVEN** el extra `tony[voice]` no instalado
- **WHEN** se ejecuta `uv run pytest`
- **THEN** todas las pruebas de voz pasan con los dobles y ninguna importa un motor real

#### Scenario: Motores reales bajo marcador
- **GIVEN** el extra instalado y los modelos en caché
- **WHEN** se ejecuta `uv run pytest -m voice`
- **THEN** se transcribe un WAV sintético con el motor real sin error y se sintetiza una frase con audio no vacío con Piper y con Kokoro

#### Scenario: Marcador excluido por defecto
- **WHEN** se ejecuta `uv run pytest` sin `-m voice`
- **THEN** las pruebas marcadas `voice` se omiten

#### Scenario: Hilos configurados
- **GIVEN** `voice.cpu_threads: 6`
- **WHEN** se cargan los motores
- **THEN** faster-whisper recibe `cpu_threads=6` y la síntesis de Kokoro se ejecuta con 6 hilos

### Requirement: Instalación opcional del extra de voz
El extra `tony[voice]` SHALL declarar `faster-whisper>=1.2,<2`, `kokoro>=0.9.4,<1`, `piper-tts>=1.8,<2`, `silero-vad>=6,<7` (con `onnxruntime` en CPU, sin extras de audio), `numpy` y `soundfile`; `espeak-ng` SHALL documentarse como dependencia del sistema. Sin el extra, `tony web` SHALL arrancar con la voz deshabilitada y el resto de comandos SHALL funcionar igual.

#### Scenario: Extra declarado
- **WHEN** se lee `pyproject.toml`
- **THEN** el extra `voice` contiene `faster-whisper`, `kokoro`, `piper-tts`, `silero-vad`, `onnxruntime`, `numpy` y `soundfile`

#### Scenario: Servidor sin el extra
- **GIVEN** el extra no instalado
- **WHEN** se ejecuta `tony web`
- **THEN** el servidor arranca y `GET /api/health` incluye `voice: {available: false, reason}`

### Requirement: Comando `tony voice bench`
`tony voice bench [--config PATH]` SHALL imprimir p50 y p95 en ms de 5 repeticiones de: carga, STT de 3 s, STT de "¿qué hora es?" sintetizado, síntesis de 12 palabras y primer fragmento de una cláusula de 4 palabras. Con `TONY_EVALS=1` SHALL medir además el primer token del `front` (`ttft`) y la ida y vuelta en streaming (`roundtrip_stream`) desde el fin del habla hasta el primer `tts.chunk`, con su desglose, marcando si su p50 supera 2500 ms.

#### Scenario: Benchmark sin modelo
- **GIVEN** el extra instalado y `TONY_EVALS` sin definir
- **WHEN** se ejecuta `tony voice bench`
- **THEN** imprime p50 y p95 de `load`, `stt_3s`, `stt_utt`, `tts_12w` y `tts_first` y no llama al modelo Claude

#### Scenario: Benchmark con ida y vuelta
- **GIVEN** `TONY_EVALS=1`
- **WHEN** se ejecuta `tony voice bench`
- **THEN** imprime además p50 y p95 de `roundtrip` (respuesta completa sin streaming, como referencia), `ttft` y `roundtrip_stream`, el desglose `endpoint`, `stt`, `ttft`, `tts_first` de la mediana y marca si p50 de `roundtrip_stream` supera 2500 ms

## ADDED Requirements

### Requirement: Fonemizador latinoamericano
La síntesis SHALL usar fonemas de español latinoamericano (`es-419`, con seseo) por defecto en todos los motores; en Kokoro el parámetro `lang` del alias SHALL admitir `es-419` (por defecto) o `es` para restaurar la pronunciación peninsular.

#### Scenario: Seseo por defecto
- **GIVEN** `voice.tts: kokoro/em_alex`
- **WHEN** se fonemiza `cielo, zapato`
- **THEN** los fonemas empiezan por `s` y no contienen `θ`

#### Scenario: Pronunciación peninsular explícita
- **GIVEN** `voice.tts: kokoro/em_alex?lang=es`
- **WHEN** se fonemiza `cielo`
- **THEN** los fonemas contienen `θ`

### Requirement: Velocidad y mezcla de voces
El parámetro `speed` del alias SHALL aceptar valores entre 0,5 y 1,5 (por defecto 1,0) y ajustar el ritmo en cualquier motor. En Kokoro la voz SHALL poder ser una mezcla ponderada `voz*peso+voz*peso` cuyos pesos sumen 1 (tolerancia 0,01); una mezcla con pesos inválidos o una voz desconocida SHALL fallar al validar.

#### Scenario: Mezcla válida
- **GIVEN** `voice.tts: kokoro/em_alex*0.6+em_santa*0.4?speed=0.94`
- **WHEN** se carga el motor
- **THEN** sintetiza con la combinación 0,6/0,4 de ambas voces a velocidad 0,94

#### Scenario: Pesos que no suman 1
- **GIVEN** `voice.tts: kokoro/em_alex*0.6+em_santa*0.6`
- **WHEN** se valida la configuración
- **THEN** falla con un mensaje en español que indica que los pesos deben sumar 1

#### Scenario: Velocidad fuera de rango
- **GIVEN** `voice.tts: piper/es_MX-ald-medium?speed=2`
- **WHEN** se valida la configuración
- **THEN** falla con un mensaje en español que indica el rango 0,5–1,5

### Requirement: Motor Piper
El motor `piper` SHALL sintetizar con voces Piper en CPU, aceptar solo las voces españolas del catálogo conocido (`es_MX-ald-medium`, `es_MX-claude-high`, `es_AR-daniela-high` y las `es_ES-*`), descargar el modelo a la caché estándar de Hugging Face en el primer uso o en `tony voice warmup` y entregar fragmentos a 24 kHz.

#### Scenario: Voz Piper desconocida
- **GIVEN** `voice.tts: piper/es_XX-nadie-low`
- **WHEN** se valida la configuración
- **THEN** falla con un mensaje en español que lista las voces Piper válidas

#### Scenario: Remuestreo a 24 kHz
- **GIVEN** una voz Piper que genera audio a 22 050 Hz
- **WHEN** se sintetiza una frase
- **THEN** cada fragmento entregado declara 24 000 Hz y su duración difiere < 1 % de la original

### Requirement: Voz por defecto de Jarvis
La voz por defecto SHALL ser masculina, de español latinoamericano neutro con seseo y con primer fragmento de una cláusula de 4 palabras en ≤ 400 ms p50 en la máquina de referencia. La elección SHALL documentarse en el README con una tabla de candidatas (voz, latencia, tono y notas) y un paquete de muestras WAV generable en `samples/voices/` (ignorado por git).

#### Scenario: Paquete de muestras
- **WHEN** se ejecuta el script de muestras de voz
- **THEN** `samples/voices/` contiene un WAV por candidata con el mismo párrafo de referencia y git no los rastrea

#### Scenario: Latencia de la voz por defecto
- **GIVEN** el extra instalado y los modelos en caché
- **WHEN** se ejecuta `tony voice bench`
- **THEN** `tts_first` tiene p50 ≤ 400 ms
