# Spec Delta

## Purpose

Define el orbe holográfico 3D que ocupa el centro de la UI web: su composición visual, la interacción del usuario, los estados que reflejan la actividad de Jarvis, su reacción al audio y sus garantías de rendimiento, accesibilidad y alternativa sin WebGL.

## ADDED Requirements

### Requirement: Orbe holográfico como pieza central
La UI SHALL mostrar a pantalla completa, detrás de la capa HUD, un orbe 3D generado proceduralmente sin recursos externos: 2–3 capas geodésicas en malla a distintos radios y ejes, 4–6 arcos parciales inclinados, estrías radiales, una nube de 3 000–6 000 partículas sobre y alrededor de las capas y un núcleo brillante, en tonos ámbar (`#ffb347`, `#ff8c1a`, núcleo `#ffd27a`) con resplandor aditivo sobre fondo casi negro. El orbe SHALL ser decorativo (`aria-hidden`).

#### Scenario: Orbe visible al cargar
- **GIVEN** un navegador con WebGL
- **WHEN** se abre la página
- **THEN** el orbe ocupa el centro de la ventana detrás de la HUD, con capas, arcos, partículas y núcleo visibles

#### Scenario: Orbe ignorado por lectores de pantalla
- **WHEN** se inspecciona el contenedor del orbe
- **THEN** tiene `aria-hidden="true"` y no recibe foco con `Tab`

### Requirement: Rotación por arrastre y zoom acotado
El usuario SHALL poder rotar el orbe arrastrando con ratón o táctil, con inercia amortiguada, y acercarlo o alejarlo con la rueda o el pellizco dentro de una distancia mínima y máxima; el desplazamiento lateral SHALL estar deshabilitado. Tras 4 s sin interacción el orbe SHALL retomar su autorrotación. Arrastrar sobre el orbe no SHALL afectar a la HUD.

#### Scenario: Arrastre rota el orbe
- **WHEN** el usuario arrastra horizontalmente sobre el orbe
- **THEN** el orbe gira en ese sentido y se detiene suavemente al soltar

#### Scenario: Zoom limitado
- **WHEN** el usuario sigue girando la rueda para acercarse más allá del límite
- **THEN** la cámara se queda en la distancia mínima

#### Scenario: Autorrotación tras inactividad
- **GIVEN** el usuario dejó de interactuar
- **WHEN** pasan 4 s
- **THEN** el orbe vuelve a rotar solo

### Requirement: Estado del orbe derivado de la app
El orbe SHALL mostrar uno de cuatro estados derivados del estado existente, con esta prioridad: `speaking` si hay voz sintetizándose o sonando; `thinking` si hay un turno o una tarea en curso o se está transcribiendo; `listening` si el micrófono está activo; `idle` en otro caso. Cada estado SHALL ser distinguible: `idle` con rotación lenta y brillo pulsante, `thinking` con arcos más rápidos y pulso marcado.

#### Scenario: Turno en curso
- **GIVEN** el micrófono apagado
- **WHEN** llega `user.accepted` y no ha llegado `assistant.final`
- **THEN** el orbe está en `thinking`

#### Scenario: Hablar tiene prioridad
- **GIVEN** el micrófono activo y una tarea en curso
- **WHEN** empieza a sonar la respuesta hablada
- **THEN** el orbe está en `speaking`

#### Scenario: Reposo
- **GIVEN** sin turno, sin tarea, micrófono apagado y sin audio
- **WHEN** se observa el orbe
- **THEN** está en `idle`

### Requirement: Reacción al nivel del micrófono
En `listening` el nivel de entrada del micrófono SHALL escalar el núcleo y las capas y agitar las partículas, de forma proporcional y acotada; con nivel 0 el orbe SHALL quedar en su pose de escucha sin agitación.

#### Scenario: Voz del usuario agita el orbe
- **GIVEN** el orbe en `listening`
- **WHEN** el nivel de entrada sube de 0 a 0,2
- **THEN** el núcleo y las capas crecen y las partículas se agitan, sin superar la escala máxima definida

### Requirement: Reacción a la voz de Jarvis
En `speaking` la amplitud real del audio reproducido SHALL deformar las capas y acelerar los arcos y la intensidad del resplandor, suavizada para evitar parpadeos; sin audio sonando la amplitud SHALL tender a 0.

#### Scenario: El orbe sigue la voz
- **GIVEN** el orbe en `speaking`
- **WHEN** la amplitud de salida alterna entre frases y silencios
- **THEN** la deformación y el resplandor suben y bajan siguiendo la voz sin saltos bruscos entre fotogramas

#### Scenario: Fin del audio
- **WHEN** la cola de reproducción termina o se pulsa "Detener audio"
- **THEN** la amplitud usada por el orbe decae a 0 y el orbe sale de `speaking`

### Requirement: Transiciones suavizadas
Los cambios de estado SHALL interpolar los parámetros visuales (velocidad, escala, resplandor, agitación) en unos 300 ms con curva suave, sin saltos; un cambio a mitad de transición SHALL partir de los valores actuales.

#### Scenario: Paso de idle a thinking
- **WHEN** el estado cambia de `idle` a `thinking`
- **THEN** la velocidad de los arcos aumenta de forma progresiva hasta su valor de `thinking` en unos 300 ms

#### Scenario: Interrupción de una transición
- **GIVEN** una transición de `thinking` a `speaking` a medio camino
- **WHEN** el estado vuelve a `thinking`
- **THEN** los parámetros vuelven desde su valor actual sin salto

### Requirement: Movimiento reducido
Con `prefers-reduced-motion: reduce` el orbe SHALL quedarse sin autorrotación ni agitación y SHALL indicar el estado solo con cambios suaves de brillo; la rotación por arrastre SHALL seguir disponible.

#### Scenario: Usuario con movimiento reducido
- **GIVEN** el sistema con `prefers-reduced-motion: reduce`
- **WHEN** Jarvis habla
- **THEN** el orbe no rota ni se deforma solo y solo varía su brillo

### Requirement: Rendimiento del render
El orbe SHALL apuntar a 60 fps a 1080p en una GPU integrada, limitar la densidad de píxeles del lienzo a 2, adaptarse al tamaño de la ventana y detener el bucle de render mientras la pestaña esté oculta, reanudándolo al volver.

#### Scenario: Pestaña oculta
- **WHEN** la pestaña pasa a oculta
- **THEN** no se programan más fotogramas hasta que vuelve a ser visible

#### Scenario: Pantalla de alta densidad
- **GIVEN** `devicePixelRatio` igual a 3
- **WHEN** se crea el lienzo
- **THEN** se renderiza con densidad 2

### Requirement: Liberación de recursos
Al desmontar el orbe la UI SHALL parar el bucle de render, quitar sus escuchas de eventos y liberar geometrías, materiales, pases de postprocesado y el contexto de render.

#### Scenario: Desmontaje limpio
- **WHEN** se desmonta el componente del orbe
- **THEN** se liberan todas sus geometrías, materiales y el renderizador, y no queda ningún fotograma programado

### Requirement: Alternativa sin WebGL
Si WebGL no está disponible o falla al crear el contexto, la UI SHALL mostrar un orbe estático en CSS con degradados radiales ámbar en lugar del 3D, sin errores visibles, y el resto de la aplicación SHALL funcionar igual.

#### Scenario: Navegador sin WebGL
- **GIVEN** un navegador sin WebGL
- **WHEN** se abre la página
- **THEN** se ve el orbe estático en CSS y el chat, la voz y el panel de debug funcionan

### Requirement: Pruebas del orbe
La lógica del orbe (mapeo de estado a parámetros, suavizado de amplitud, interpolación y generadores de geometría) SHALL probarse en Vitest como funciones puras, y el componente SHALL probarse con un renderizador simulado en `jsdom` sin WebGL real.

#### Scenario: Pruebas sin GPU
- **WHEN** se ejecuta `npm test`
- **THEN** las pruebas del mapeo de estados, el suavizado, las geometrías y el montaje y desmontaje del orbe pasan en `jsdom`
