# Tasks

Todas las rutas son relativas a `tony/apps/web/frontend`. Cada módulo sigue Rojo → Verde → Refactor: la prueba Vitest que falla se escribe y se ve fallar antes del código.

## 1. Dependencias

- [x] 1.1 Instalar `three@0.186.1` y `@types/three@0.186.0` con `npm install --save-exact`; verificar que `package.json` las fija sin `^` y que `npm ls three` y `npm run lint` pasan

## 2. Lógica pura del orbe (`src/orb/`)

- [x] 2.1 Rojo: `orbState.test.ts` con la tabla de prioridad (`speaking` > `thinking` > `listening` > `idle`), incluidos `player.playing` sin fase, `transcribing` y `activeRootId` sin turno; verificar que falla
- [x] 2.2 Verde: implementar `deriveOrbState` en `orbState.ts`; verificar que 2.1 pasa
- [x] 2.3 Rojo: `tween.test.ts` para `approach`/`approachParams` (dt 0, dt = τ ≈ 63 %, dt acotado a 100 ms, interrupción parte del valor actual); verificar que falla
- [x] 2.4 Verde: implementar `tween.ts`; verificar que 2.3 pasa
- [x] 2.5 Rojo: `amplitude.test.ts` para `rms` (silencio, seno, saturación) y `AmplitudeSmoother` (ataque ~40 ms, caída ~180 ms, independencia de dt, rango [0,1]); verificar que falla
- [x] 2.6 Verde: implementar `amplitude.ts`; verificar que 2.5 pasa
- [x] 2.7 Rojo: `orbParams.test.ts` por estado (valores de `idle`/`thinking` distintos), nivel 0/0,2/>1 con escala acotada, amplitud 0/1 en `speaking` y anulación de movimiento con `reducedMotion`; verificar que falla
- [x] 2.8 Verde: implementar `targetParams` en `orbParams.ts`; verificar que 2.7 pasa
- [x] 2.9 Rojo: `geometry.test.ts` para los generadores con semilla (conteos de vértices, radios dentro de tolerancia, arcos con barrido parcial, partículas 3 000–6 000, determinismo) y un *golden file* con `toMatchFileSnapshot` del resumen JSON; verificar que falla
- [x] 2.10 Verde: implementar `geometry.ts`; verificar que 2.9 pasa
- [x] 2.11 Refactor del grupo con las pruebas en verde; verificar `npm test` y `npm run lint`

## 3. Amplitud de la reproducción (`web-ui-voice`)

- [x] 3.1 Rojo: ampliar `audio/player.test.ts` con `createAnalyser` en el `AudioContext` falso: cada fuente conecta al analizador y este a `destination`, la programación sin huecos no cambia, `amplitude()` en (0,1] con datos, y 0 sin contexto y tras `stop()`; verificar que falla
- [x] 3.2 Verde: añadir el analizador y `amplitude()` a `PcmPlayer`, y exponer `amplitude` estable desde `usePcmPlayer`; verificar que 3.1 y las pruebas de voz existentes pasan

## 4. Adaptador de escena Three.js

- [x] 4.1 Rojo: `orb/scene.test.ts` con renderizador y composer falsos inyectados: crea capas, arcos, estrías, partículas y núcleo; `update` aplica `OrbParams` a uniforms/escalas; `resize` usa DPR ≤ 2; `dispose` llama a `dispose` de cada geometría, material, textura, composer y renderizador; verificar que falla
- [x] 4.2 Rojo: `orb/webgl.test.ts` para `isWebGLAvailable` con `getContext` que devuelve contexto, `null` o lanza; verificar que falla
- [x] 4.3 Verde: implementar `scene.ts` (D5) y `webgl.ts`; verificar que 4.1 y 4.2 pasan

## 5. Componente del orbe

- [x] 5.1 Rojo: `orb/OrbStage.test.tsx` con escena simulada, rAF y temporizadores falsos: `aria-hidden` y `data-orb-state`; bucle se pausa con la pestaña oculta y se reanuda; desmontaje cancela rAF y llama a `dispose`; sin WebGL, error de creación o `webglcontextlost` muestran `OrbFallback`; `prefers-reduced-motion` llega a `targetParams` y desactiva autorrotación; `getAmplitude` se lee por fotograma sin re-render; verificar que falla
- [x] 5.2 Rojo: pruebas de interacción: controles con `enablePan=false`, damping y `minDistance`/`maxDistance`; autorrotación se para al arrastrar y vuelve a los 4 s; verificar que falla
- [x] 5.3 Verde: implementar `OrbStage.tsx` y `OrbFallback.tsx`; verificar que 5.1 y 5.2 pasan

## 6. Disposición HUD (`web-ui-chat`, `web-ui-debug-panel`)

- [x] 6.1 Rojo: `Subtitles.test.tsx` (último usuario y último asistente, deltas sin duplicar, `WaitBubble`, estado vacío "Escribe a Jarvis…", markdown saneado, `aria-live="polite"`); verificar que falla
- [x] 6.2 Rojo: `TranscriptDrawer.test.tsx` (`aria-expanded`, lista completa con etiquetas de modo, `Escape` cierra y devuelve el foco, sin `aria-live`); ajustar `ChatList` con prop `live`; verificar que falla
- [x] 6.3 Rojo: `ConfirmationCard.test.tsx` añade foco inicial en `Rechazar`; `HudBar.test.tsx` comprueba que entrada, micrófono, estado de voz, selector, "Detener audio" y "Cancelar tarea" están en la barra y conservan sus manejadores; verificar que falla
- [x] 6.4 Rojo: actualizar `styles.test.ts` a un único tema oscuro (contraste AA de `--fg`, `--muted`, `--warn`, `--accent` sobre `--bg` y `--surface`), `color-scheme: dark`, `:focus-visible`, `prefers-reduced-motion`, `max-width: 80ch` y cajón del debug fijo a la derecha; verificar que falla
- [x] 6.5 Verde: implementar `Subtitles`, `TranscriptDrawer`, `HudBar`, foco de `ConfirmationCard`, `styles.css` (capas `.stage`/`.hud`, vidrio, tokens) e `index.html` (`color-scheme` oscuro, fuentes con `display=swap` y reserva); verificar que 6.1–6.4 y las pruebas de `DebugPanel` existentes pasan

## 7. Integración en `App`

- [x] 7.1 Rojo: ampliar `App.test.tsx`: `user.accepted` deja el orbe en `thinking`, `tts.start` + chunk en `speaking`, micrófono activo en `listening`, reposo en `idle` (vía `data-orb-state`); subtítulos y cajón muestran el historial; todas las pruebas de `App` existentes siguen pasando con la nueva disposición; verificar que falla
- [x] 7.2 Verde: componer `OrbStage` + HUD en `App.tsx`, pasando `deriveOrbState`, `mic.level` y `player.amplitude`; verificar que 7.1 y `npm test` completo pasan
- [x] 7.3 Refactor (SRP en `App.tsx`, nombres autoexplicativos); verificar `npm test` y `npm run lint`
- [x] 7.4 Mutación con Stryker vía `npx` solo sobre `src/orb/{orbState,orbParams,tween,amplitude,geometry}.ts` y `src/audio/player.ts`, abortando a los 3 min; verificar puntuación > 95 % o justificar cada mutante superviviente en el resumen de la tarea

## 8. Verificación final

- [ ] 8.1 Ejecutar `npm test`, `npm run lint` y `npm run build` en `tony/apps/web/frontend`; verificar que los tres terminan sin errores
- [ ] 8.2 Ejecutar `uv run pytest -q` en la raíz; verificar que la suite Python pasa sin haber tocado código Python (`git diff --stat` sin ficheros `.py`)
- [x] 8.3 Con `uv run tony web` sirviendo en `127.0.0.1:8787` (reutilizar si ya está activo; recargar tras el build), ejecutar un script Playwright desde el scratchpad (Chromium headless, `--use-angle=swiftshader`, medios falsos) que capture `idle`, `listening`, `thinking` y `speaking` forzados con `routeWebSocket`/`route` según D8; guardar `openspec/changes/tony-06-jarvis-orb-ui/screenshots/{idle,listening,thinking,speaking}.png`, verificar que cada PNG pesa < 1 MB y que `data-orb-state` coincide en cada captura
- [x] 8.4 Verificación manual en la GPU AMD integrada a 1080p: fps ≈ 60 en `idle` y `speaking` (DevTools → Rendering → FPS meter), rotación por arrastre, zoom acotado, autorrotación a los 4 s y movimiento reducido activado en el sistema
- [x] 8.5 Crear la rama `feat/jarvis-orb-ui` y commit con `feat(web-ui): add jarvis holographic orb and hud layout`, sin trailer `Co-Authored-By` ni atribución a IA; verificar con `git log -1 --format=%B`

## Workflow follow-up

- Archivar el cambio tras la revisión de las capturas y sincronizar las specs principales.
