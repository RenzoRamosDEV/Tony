# Spec Delta

## Purpose

Define los puertos de voz de Tony (detección de actividad, transcripción y síntesis), sus contratos de entrada y salida, los motores locales que los implementan, su instalación opcional, la carga única de modelos fuera del bucle de eventos y las utilidades `tony voice warmup` y `tony voice bench`.

## ADDED Requirements

### Requirement: Puerto de detección de actividad de voz
El detector de voz SHALL recibir audio PCM Float32 a 16 kHz mono en fragmentos y devolver cero o más intervenciones completas por llamada, manteniendo estado por sesión. Una intervención SHALL terminar tras ≥ 700 ms de silencio después de habla; los tramos con < 300 ms de habla (sin contar silencios interiores) SHALL descartarse; una intervención SHALL cortarse forzosamente a los 30 s de duración acumulada, alterne o no habla y silencio.

#### Scenario: Silencio cierra la intervención
- **GIVEN** un detector nuevo que recibe 1,5 s de habla seguidos de 700 ms de silencio
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
- **GIVEN** dos ventanas de habla separadas por 20 ventanas de silencio (64 ms de habla)
- **WHEN** se cierra la intervención
- **THEN** se descarta aunque dure más de 300 ms

#### Scenario: Silencio insuficiente no cierra
- **GIVEN** 1 s de habla, 500 ms de silencio y 1 s de habla
- **WHEN** se alimentan los fragmentos
- **THEN** no se devuelve ninguna intervención hasta que lleguen ≥ 700 ms de silencio

### Requirement: Puerto de transcripción
El transcriptor SHALL recibir una intervención y devolver `{text, language, duration_ms}` donde `language` es el idioma fijado por `persona.language` del `front` (`es` por defecto; `en` si el `front` es `en`) y `duration_ms` la duración del audio. Un audio sin habla reconocible SHALL devolver `text` vacío sin error.

#### Scenario: Idioma del front
- **GIVEN** un `front` con `persona.language: "en"`
- **WHEN** se transcribe una intervención
- **THEN** el motor recibe `language="en"` y la transcripción devuelve `language: "en"`

#### Scenario: Audio sin habla
- **WHEN** se transcribe una intervención de ruido sin palabras
- **THEN** devuelve `text: ""` y `duration_ms` igual a la duración del audio

### Requirement: Puerto de síntesis
El sintetizador SHALL recibir un texto y una voz, y devolver un flujo de fragmentos de audio PCM Int16 a 24 kHz mono que el pipeline consume de forma asíncrona (frase a frase en el ejecutor de voz). La voz SHALL tomarse del alias de configuración `voice.tts` con el formato `motor/voz` (por defecto `kokoro/ef_dora`); un alias cuyo motor o voz no existan SHALL fallar al cargar el motor con un mensaje en español que nombre el alias.

#### Scenario: Flujo de fragmentos
- **WHEN** se sintetiza `Buenos días, señor.` con `kokoro/ef_dora`
- **THEN** se obtienen uno o más fragmentos PCM Int16 a 24 kHz mono cuya duración total es mayor que 0

#### Scenario: Alias inválido
- **GIVEN** `voice.tts: kokoro/no_existe`
- **WHEN** se carga el motor de síntesis
- **THEN** falla con un mensaje en español que contiene `kokoro/no_existe`

### Requirement: Motores locales y dobles de prueba
El sistema SHALL ofrecer motores locales Silero (detección), faster-whisper `small` en CPU con cómputo `int8` (transcripción) y Kokoro con `lang_code` español y voz `ef_dora` (síntesis), y dobles equivalentes para pruebas: detección por umbral de energía, transcripción con texto fijado y síntesis de una onda senoidal. La suite estándar SHALL usar solo los dobles; los motores reales SHALL probarse únicamente con el marcador `voice`.

#### Scenario: Suite estándar sin motores
- **GIVEN** el extra `tony[voice]` no instalado
- **WHEN** se ejecuta `uv run pytest`
- **THEN** todas las pruebas de voz pasan con los dobles y ninguna importa un motor real

#### Scenario: Motores reales bajo marcador
- **GIVEN** el extra instalado y los modelos en caché
- **WHEN** se ejecuta `uv run pytest -m voice`
- **THEN** se transcribe un WAV sintético con el motor real sin error y se sintetiza una frase con audio no vacío

#### Scenario: Marcador excluido por defecto
- **WHEN** se ejecuta `uv run pytest` sin `-m voice`
- **THEN** las pruebas marcadas `voice` se omiten

### Requirement: Carga única y ejecución fuera del bucle de eventos
Cada motor SHALL cargarse una sola vez por proceso (carga perezosa en el primer uso o anticipada con `warmup`) y todo el trabajo de CPU de detección, transcripción y síntesis SHALL ejecutarse en un ejecutor dedicado de como máximo 2 hilos, de modo que el bucle de eventos nunca se bloquee.

#### Scenario: Dos transcripciones comparten el modelo
- **WHEN** se transcriben dos intervenciones consecutivas
- **THEN** el modelo se construye una sola vez

#### Scenario: El bucle sigue respondiendo
- **GIVEN** una síntesis que tarda 2 s en el motor
- **WHEN** se ejecuta mientras el servidor atiende un `hello`
- **THEN** el `hello.ok` se responde antes de que termine la síntesis

### Requirement: Instalación opcional del extra de voz
El extra `tony[voice]` SHALL declarar `faster-whisper>=1.2,<2`, `kokoro>=0.9.4,<1`, `silero-vad>=6,<7` (con `onnxruntime` en CPU, sin extras de audio), `numpy` y `soundfile`; `espeak-ng` SHALL documentarse como dependencia del sistema. Sin el extra, `tony web` SHALL arrancar con la voz deshabilitada y el resto de comandos SHALL funcionar igual.

#### Scenario: Extra declarado
- **WHEN** se lee `pyproject.toml`
- **THEN** el extra `voice` contiene `faster-whisper`, `kokoro`, `silero-vad`, `onnxruntime`, `numpy` y `soundfile`

#### Scenario: Servidor sin el extra
- **GIVEN** el extra no instalado
- **WHEN** se ejecuta `tony web`
- **THEN** el servidor arranca y `GET /api/health` incluye `voice: {available: false, reason}`

### Requirement: Comando `tony voice warmup`
`tony voice warmup [--config PATH]` SHALL descargar los modelos a la caché estándar si faltan, cargar los tres motores y terminar con código `0` imprimiendo el tiempo de carga de cada uno; sin el extra SHALL terminar con código `2` y un mensaje en español que indique `uv sync --extra voice`.

#### Scenario: Warmup correcto
- **GIVEN** el extra instalado
- **WHEN** se ejecuta `tony voice warmup`
- **THEN** imprime una línea por motor con su tiempo de carga y termina con código `0`

#### Scenario: Warmup sin el extra
- **WHEN** se ejecuta `tony voice warmup` sin el extra
- **THEN** termina con código `2` y el mensaje contiene `uv sync --extra voice`

### Requirement: Comando `tony voice bench`
`tony voice bench [--config PATH]` SHALL medir en la máquina la carga de modelos, la transcripción de una muestra sintética de 3 s y la síntesis de una frase de 12 palabras, e imprimir p50 y p95 de 5 repeticiones por medida en milisegundos. Con `TONY_EVALS=1` SHALL medir además la ida y vuelta completa "¿qué hora es?" desde el fin del habla hasta el primer fragmento de audio. El objetivo documentado es p50 < 2 s con modelos precargados.

#### Scenario: Benchmark sin modelo
- **GIVEN** el extra instalado y `TONY_EVALS` sin definir
- **WHEN** se ejecuta `tony voice bench`
- **THEN** imprime p50 y p95 de `load`, `stt_3s` y `tts_12w` y no llama al modelo Claude

#### Scenario: Benchmark con ida y vuelta
- **GIVEN** `TONY_EVALS=1`
- **WHEN** se ejecuta `tony voice bench`
- **THEN** imprime además p50 y p95 de `roundtrip` y marca si p50 supera 2000 ms

### Requirement: Muestras de audio sintéticas
Las muestras de audio de prueba SHALL ser WAV cortos generados sintéticamente (tonos, ruido y silencio) sin voz humana real, versionados en el repositorio y reutilizados por el benchmark.

#### Scenario: Fixtures sin voz humana
- **WHEN** se inspeccionan las muestras de prueba
- **THEN** cada una dura ≤ 3 s, es PCM 16 kHz mono y se genera a partir de parámetros deterministas
