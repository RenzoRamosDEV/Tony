# Design

## Context

- Frontend React 18 + Vite 8 + Vitest 5 (`jsdom`) en `tony/apps/web/frontend`; `uv run tony web` sirve `dist` desde disco.
- `App.tsx` ya concentra el estado que necesita el orbe: `state.voice` (`mic`, `phase`), `state.turnInProgress`, `state.activeRootId`, `player.playing` y `mic.level` (RMS cuantizado a pasos de 0,02, un valor cada ~30 ms) de `useMicCapture`.
- `PcmPlayer` (`audio/player.ts`) conecta cada `AudioBufferSourceNode` directamente a `context.destination`; no hay punto de lectura de la señal de salida.
- `styles.test.ts` comprueba contraste AA de un tema claro y uno oscuro leyendo variables hex de `styles.css`, más `:focus-visible`, `prefers-reduced-motion` y `max-width: 80ch`.
- Motivación y alcance: ver proposal.md. Requisitos: ver `specs/web-ui-orb`, `specs/web-ui-chat`, `specs/web-ui-voice`, `specs/web-ui-debug-panel`.

## Goals / Non-Goals

**Goals:**
- Lógica del orbe pura y probada sin GPU; Three.js confinado a un único adaptador.
- Cero re-renders de React por fotograma: la amplitud se lee por *pull* dentro del bucle de render.
- Mantener todas las pruebas de comportamiento existentes (protocolo, voz, debug) con cambios solo de ubicación en el DOM.

**Non-Goals:**
- Cambios en protocolo WebSocket, API HTTP o backend Python.
- Personalización del orbe por el usuario (colores, densidad) o temas claros.
- Medición automatizada de fps en CI (SwiftShader no es representativo).

## Decisions

### D1. Three.js plano, sin @react-three/fiber
- `three@0.186.1` y `@types/three@0.186.0`, versión exacta (`--save-exact`). Addons desde `three/addons/` (`OrbitControls`, `EffectComposer`, `RenderPass`, `UnrealBloomPass`, `OutputPass`).
- Alternativa descartada: `@react-three/fiber` + `drei`. Añade reconciliador y dos dependencias para una escena estática de ~10 objetos con un único bucle; el ciclo de vida imperativo (crear/actualizar/liberar) es más simple de probar con un renderizador falso que montando un reconciliador en `jsdom`.

### D2. Módulos y fronteras (puertos y adaptadores)
```
src/orb/
  orbState.ts     deriveOrbState(inputs) -> "idle"|"listening"|"thinking"|"speaking"   (puro)
  orbParams.ts    targetParams(state, level, amplitude, reducedMotion) -> OrbParams      (puro)
  tween.ts        approach(current, target, dtMs, tauMs) / approachParams(...)            (puro)
  amplitude.ts    rms(samples) y AmplitudeSmoother (ataque/caída)                         (puro)
  geometry.ts     generadores con semilla -> Float32Array (aristas geodésicas, arcos,
                  estrías, partículas)                                                     (puro)
  scene.ts        createOrbScene(canvas, deps) -> { update(params, dtMs), resize(w,h,dpr),
                  dispose() }   — único módulo que importa three                          (adaptador)
  webgl.ts        isWebGLAvailable(document)                                               (adaptador)
  OrbStage.tsx    componente: bucle rAF, visibilidad, resize, reduced motion, fallback
  OrbFallback.tsx orbe CSS estático
```
- `OrbParams`: `spin`, `ringSpeed`, `coreScale`, `shellScale`, `displacement`, `agitation`, `bloom`, `glow` (números planos).
- `scene.ts` recibe por `deps` las factorías `createRenderer` y `createComposer`; en pruebas se inyectan falsos. Geometrías y materiales de Three.js sí se construyen en `jsdom` (no requieren contexto WebGL).
- Prioridad de estados en `deriveOrbState`: `speaking` (`voice.phase === "speaking"` o `player.playing`) > `thinking` (`turnInProgress`, `activeRootId !== null` o `phase === "transcribing"`) > `listening` (`mic === "on"`) > `idle`. Mismo criterio de "hablando" que ya usa `App.tsx`.

### D3. Ruta del audio hacia el orbe
- `PcmPlayer` crea un `AnalyserNode` (`fftSize` 512, `smoothingTimeConstant` 0) junto al contexto; cada fuente se conecta a él y él a `destination` (pasivo, no altera la señal). Nuevo método `amplitude(): number` que lee `getFloatTimeDomainData`, calcula RMS y normaliza a [0,1] con el mismo fondo de escala que `VoiceStatus` (RMS 0,2); devuelve 0 sin contexto o tras `stop()`.
- `usePcmPlayer` expone `amplitude` como función estable; `OrbStage` la recibe como `getAmplitude` y la invoca dentro del rAF. El nivel del micrófono llega como prop (ya es estado cuantizado) y se guarda en una ref.
- `AmplitudeSmoother`: ataque ~40 ms, caída ~180 ms, independiente de la tasa de fotogramas (`dtMs`).
- Alternativa descartada: publicar la amplitud como estado de React → 60 re-renders/s de `App`.

### D4. Animación y transiciones
- Cada fotograma: `target = targetParams(...)`; `current = approachParams(current, target, dtMs, 300)` con aproximación exponencial (`1 - exp(-dt/τ)`), que parte siempre del valor actual (interrupciones sin salto). `dtMs` se acota a 100 ms para que volver de pestaña oculta no provoque saltos.
- Desplazamiento de capas y agitación de partículas en GPU: `ShaderMaterial` mínimo con uniforms `uTime`, `uDisplacement`, `uAgitation` (ruido trigonométrico barato); sin bucles CPU sobre 6 000 puntos.
- Reduced motion (`matchMedia('(prefers-reduced-motion: reduce)')`, escuchado en vivo): `targetParams` anula `spin`, `ringSpeed`, `displacement` y `agitation`, y solo varía `glow`/`bloom`; `controls.autoRotate = false`.

### D5. Composición y rendimiento
- Agrupación para pocas *draw calls* (~10): cada capa geodésica es un `LineSegments` con `EdgesGeometry` de `IcosahedronGeometry` (detalle 2–4); arcos y estrías fusionados en un `LineSegments` por grupo; partículas en un `Points`; núcleo como `Sprite` con textura radial generada en un canvas 2D. Todo con `AdditiveBlending`, `depthWrite: false`.
- `UnrealBloomPass` a media resolución + `OutputPass`. Fondo `#05070a`.
- `renderer.setPixelRatio(Math.min(devicePixelRatio, 2))`; `ResizeObserver` sobre el contenedor; `visibilitychange` cancela/reanuda el rAF; ninguna asignación por fotograma.
- `OrbitControls`: `enablePan = false`, `enableDamping = true`, `minDistance`/`maxDistance` acotados, `autoRotate` desactivado en `start` y reactivado con un temporizador de 4 s tras `end`.

### D6. Alternativa sin WebGL y liberación
- `isWebGLAvailable` prueba `canvas.getContext('webgl2') ?? getContext('webgl')`; si falla, o `createOrbScene` lanza, o llega `webglcontextlost`, `OrbStage` muestra `OrbFallback` (degradados radiales en CSS con brillo por estado vía `data-orb-state`).
- `dispose()`: cancela rAF, quita escuchas, `controls.dispose()`, `geometry.dispose()`/`material.dispose()`/texturas de cada objeto recorrido, `composer.dispose()`, `renderer.dispose()`.
- El contenedor lleva `aria-hidden="true"` y `data-orb-state` (sirve a la alternativa CSS, a las pruebas y a las capturas).

### D7. Disposición HUD
- Capas: `.stage` (`position: fixed; inset: 0`, orbe) y `.hud` encima con `pointer-events: none` salvo en sus paneles, para que el arrastre llegue al lienzo.
- Componentes nuevos: `HudBar` (agrupa `Composer`, `MicButton`, `VoiceStatus`, `ModeSelector`, `StopAudioButton`, `Cancelar tarea`), `Subtitles` (último mensaje de usuario y último del asistente o `WaitBubble`, reutiliza `MessageBubble`; región `aria-live="polite"`), `TranscriptDrawer` (reutiliza `ChatList` con nueva prop `live={false}` para no duplicar anuncios; `Escape` cierra y devuelve el foco).
- `ConfirmationCard` mantiene su lógica; cambia a tarjeta centrada (modal no bloqueante, sin trampa de foco) y enfoca `Rechazar` al aparecer (opción segura por defecto).
- `DebugPanel`: solo CSS (cajón fijo a la derecha, translúcido, `z-index` sobre la HUD); su lógica y persistencia no cambian.
- Tema único oscuro: un solo bloque `:root` con tokens hex (`--bg`, `--surface` opaco equivalente al vidrio en el peor caso, `--fg`, `--muted`, `--accent` ámbar, `--warn`, `--accent-fg`); `meta color-scheme` = `dark`.
- Tipografía: `Rajdhani` (texto) y `Orbitron` (título) desde Google Fonts con `display=swap` y pila de reserva `ui-monospace, "DejaVu Sans Mono", monospace`. Alternativa: autoalojar fuentes (más dependencias y peso del repo); con la reserva, sin red la app funciona igual.

### D8. Estrategia de pruebas
- Puras (Vitest, partición de equivalencias y valores límite): prioridad de estados, límites de escala con nivel 0/0,2/>1, `approach` con `dt` 0/τ/acotado, suavizado ataque/caída, generadores (conteos, radios, determinismo con semilla; *golden file* con un resumen JSON por `toMatchFileSnapshot`).
- Adaptador: `createOrbScene` con renderizador y composer falsos; espías de `dispose` en geometrías y materiales.
- Componente: `vi.mock('./scene')` o deps inyectadas; rAF y temporizadores falsos; `matchMedia` y `visibilityState` simulados.
- Voz: `AudioContext` falso existente ampliado con `createAnalyser`.
- Visual: Playwright (Chromium headless, `--use-angle=swiftshader`) contra la app real; los estados se fuerzan con `page.routeWebSocket` (pasarela al servidor real inyectando `user.accepted`, `tts.start`, `tts.chunk.meta` + frame PCM16, según `ws-chat-protocol`) y `page.route('/api/health')` + medios falsos de Chromium para `listening`. Sin ganchos de prueba en el código de producción.
- Mutación: Stryker vía `npx` (sin añadir dependencia) solo sobre `src/orb/*.ts` puros y `audio/player.ts`, con tope de 3 min.

## Risks / Trade-offs

- [Bundle +~170 KB gzip por Three.js] → importar solo clases usadas (tree-shaking de `three` ESM); se acepta por ser app local.
- [GPU integrada por debajo de 60 fps con bloom] → bloom a media resolución, DPR ≤ 2, detalle geodésico y número de partículas como constantes ajustables en `geometry.ts`; verificación manual en el equipo objetivo.
- [SwiftShader lento o distinto al hardware] → capturas solo como revisión visual, tras una espera fija; no se usan para rendimiento.
- [Contraste sobre vidrio translúcido variable] → `--surface` opaco de referencia en las pruebas y velo oscuro mínimo bajo el texto.
- [Tema oscuro fijo rompe la preferencia clara] → decisión de producto (BREAKING visual en proposal.md); el contraste AA se mantiene.
- [Fuentes de Google = petición externa] → `display=swap` y reserva local; sin red no hay bloqueo.
- [Analizador en la cadena de audio] → nodo pasivo; prueba de que la programación sin huecos no cambia.

## Migration Plan

- Solo frontend: `npm install` con las dos dependencias exactas, `npm run build`; el servidor sirve el nuevo `dist` al recargar.
- Sin migración de datos; la clave de plegado del panel de debug en el navegador se conserva.
- Rollback: revertir el commit y reconstruir `dist`.
