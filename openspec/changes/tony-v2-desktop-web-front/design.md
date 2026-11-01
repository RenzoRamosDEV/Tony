# Design

## Context

- Motivation and scope: see proposal.md. Behaviour: see the `desktop-app`, `desktop-integration`, `core-events` and `flatpak-packaging` deltas.
- Today `app.py` wires `CoreThread` (core in `tony-core` thread) → `QtEventBridge.event` (queued Qt signal) → `MainWindow.dispatch` → `Presenters.apply` (chat, activity, Edith, PIN, voice, tray). `MainWindow.dispatched` also feeds `ConfirmationAttention` (notifications). Commands go `core.submit(dict)` → `CoreRuntime.submit` → `parse_command` (pydantic, extra fields forbidden, errors name type/field but never values).
- `parse_command` also accepts the internal `stop` command used by `CoreThread` on close.
- `Speaker._play` blocks on `AudioOutput.play(clip)` with the whole clip known up front; `Listener._detect_window` sees each 32 ms microphone window on `tony-vad`. `VoiceService` publishes only through `post` onto the core loop.
- The v1 front (`git show main:tony/apps/web/frontend/...`) is self-contained React; its orb is already amber/gold and its state machine knows `idle/listening/thinking/speaking`. `orb/amplitude.ts` imports `rms` from `audio/level.ts` (not ported).
- `pyside6` already installs Qt WebEngine (`pyside6-webengine` in `packaging/requirements.txt`).

## Goals / Non-Goals

**Goals:**
- Reuse the v1 page code with minimal edits; all UI state lives in one pure TS reducer fed by core events.
- Keep every Python decision Qt-free and mutation-testable; Qt classes stay thin glue (already in `do_not_mutate` under `widgets/*` and `app.py`).
- No new runtime Python dependency; no new npm dependency beyond v1's pinned set.

**Non-Goals:**
- Chat history across page reloads or app restarts (only state-carrying events are replayed).
- Flathub-compliant offline npm sources.
- Hot reload / Vite dev server against the live core.

## Decisions

### D1. Page hosting: `QWebEngineView` + `file://`, not an HTTP server or custom scheme
`widgets/web_view.py` builds a `TonyPage(QWebEnginePage)` on an off-the-record profile and loads `QUrl.fromLocalFile(dist/index.html)`. Settings: `LocalContentCanAccessFileUrls=True` (lets Chromium load the ES module entry and the lazy three.js chunk from `file://`), `LocalContentCanAccessRemoteUrls=False` (no remote subresources), context menu disabled (no "Reload"/"Inspect"). Vite builds with `base: "./"` and `modulePreload.polyfill: false`.
- Alternative: custom `QWebEngineUrlScheme` handler (`tony://app/`). Gives a non-opaque origin, but needs scheme registration before `QApplication` exists (awkward with pytest-qt) and ~60 more lines. Kept as the fallback if the smoke run (task 9.3) shows `file://` module loading fails.
- Alternative: FastAPI static server (v1). Rejected: opens a port, out of scope.

### D2. Navigation and permission policy as pure functions
`page_policy.py` (Qt-free): `navigation_decision(url, home) -> "allow" | "external" | "block"` — `allow` only for exactly `home` (ignoring fragment), `external` for `http`/`https` link clicks, `block` for everything else (`file:` elsewhere, `javascript:`, `data:`, `mailto:`, custom schemes). `TonyPage.acceptNavigationRequest` calls it and `QDesktopServices.openUrl` on `external`. `createWindow` returns `None` (no popups). `permissionRequested` → `permission.deny()` for every permission type. The ported Markdown hook drops `target="_blank"` so links arrive as main-frame link clicks.
- `page_policy.py` also owns `web_dist(root_pkg) -> Path` and the missing-build message text.

### D3. Bridge object over `QWebChannel`
`page_bridge.py` `PageBridge(QObject)`, registered as `tony`:
- `event = Signal(str)` — JSON of each core event.
- `focusConfirmation = Signal()` — notification click.
- `@Slot(str) send(text)`, `@Slot() ready()`, `@Slot(result=str) auditToday()`.

`qwebchannel.js` is injected by Python as a `QWebEngineScript` (DocumentCreation, MainWorld) from Qt's own resource `:/qtwebchannel/qwebchannel.js` — nothing vendored, no npm package. The page's `bridge/channel.ts` wraps `qt.webChannelTransport` behind a small `TonyBridge` interface; tests use a fake.
- Alternative: `runJavaScript` push + title/console hacks. Rejected: no typed slots, ordering issues.

### D4. Command gate and replay are Qt-free
`page_protocol.py`:
- `PageCommandGate.accept(text) -> Accepted(dict) | Rejected(error_event)`: `json.loads` (malformed → `error` source `page`), `parse_command` (→ `error` with the command type as source and the `InvalidCommand` message, which never contains values), `stop` refused (→ `error` source `stop`). Accepted dicts go to `CoreThread.submit`; the core validates again (defence in depth, no behaviour change).
- `EventReplay.observe(event)` keeps the latest `voice_state`, `reply_mode`, `auth`, `mcp_status` per `(agent, server)` and the pending `needs_confirmation` (cleared by `tool_call` or task `result` with the same `task_id`); `snapshot()` returns them in that order. `voice_level` is never stored.
- Page readiness: `PageBridge` drops events until `ready()`; on `ready()` it emits `snapshot()` then forwards live. Bounded memory, survives a renderer crash + reload.
- Alternative: buffer every event until ready. Rejected: unbounded and replays partial streams.

### D5. Audit rows through the bridge
`presenters/audit.py` keeps the date-filter/row logic of the removed `EdithPresenter` (`read_audit` + `select_lines` for the local day) as `audit_today(root, now) -> list[dict]` with exactly `time, agent, tool, verdict, rule, user_decision`. Arguments are never included (strongest masking). The page appends live rows from `tool_call` events.

### D6. `voice_level` produced in the core
`tony/core/voice/levels.py` (pure, stdlib `array('f')` + `math`, no numpy):
- `level(pcm) = min(1, rms/0.2)` rounded to 2 decimals.
- `envelope(clip, frame_ms=50) -> list[float]`.
- `LevelMeter`: `set_input(level)`/`clear_input()`, `start_output(envelope, now)`/`stop_output()`, `sample(now) -> (source, level) | None` (output wins; output ends past the envelope).
- Wiring: `Listener` reports each window's level and clears on session end; `Speaker` starts the output envelope just before `play` and stops it after `play` returns or on `stop_speaking`; `VoiceService` runs a `tony-level` ticker thread (50 ms, injected clock/interval) that posts `core_events.voice_level(source, level)` through `post` only when `sample` is not `None`, and stops it in `close`.
- Alternative: levels computed in the page from audio. Rejected: audio must never leave the core.

### D7. Page state: one reducer, level outside React state
`state/reducer.ts` maps core events + local actions to `UiState` (messages, reply mode, voice state, activity tree, servers, audit rows/filter, pending confirmation, auth/PIN view, orb inputs). It ports the behaviour of the removed Python presenters (chat write decision, transcript bubble, agent colours, activity grouping `<agent>/<subagent>`, MCP red when down, PIN messages and back-off). `deriveOrbState(inputs, now)` follows the spec priority. `voice_level` events update a ref (`levelRef`) and `lastOutputAt`, not reducer state, so the 20 Hz stream re-renders only the orb loop; a 100 ms timer re-evaluates `speaking` decay.
- `orbParams.ts` gains a `confirming` case (slow strong pulse, low spin); the stage adds an Edith-amber (`#E0A100`) CSS halo on `[data-orb-state="confirming"]`. The scene colours are unchanged.
- `amplitude.ts` drops the `audio/level` import; `normalizeLevel` becomes identity-clamp because the core already normalises.
- Markdown: v1 `markdown.ts` with marked's `html` renderer overridden to escape raw HTML (keeps the existing "Raw HTML escaped" scenario) and DOMPurify kept as a second layer.

### D8. Python UI after the change
- Removed: `widgets/{chat_view,activity_panel,edith_panel,pin_dialog}.py`, `presenters/{chat,activity,edith,pin,voice,markdown,bundle}.py`. Kept: `presenters/{tray,attention,observable}.py` (`NEUTRAL` moves into `tray.py`).
- `MainWindow(tray_presenter, content, on_close)`: central widget is the web view or a `QLabel` with the build command; `dispatch(event)` → tray apply, bridge publish, `dispatched` signal; `reveal(confirmation=False)` raises and, when `True`, focuses the view and emits `focusConfirmation`.
- `open_desktop` takes an injectable `view_factory` so default tests use a fake view; `launch` imports `PySide6.QtWebEngineWidgets` before creating `QApplication` (required by Qt WebEngine).

### D9. Build and packaging
- `tony/apps/desktop/web/` copies v1 `package.json`/`package-lock.json` (same pinned versions, renamed `tony-desktop`), `tsconfig.json`, `vite.config.ts` (no proxy, `base: "./"`). `index.html` drops Google Fonts (`font-family` falls back to local fonts) and adds a CSP meta (`default-src 'self' file:; script-src 'self' file:; style-src 'self' file: 'unsafe-inline'; img-src 'self' file: data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'`).
- Hatch wheel: `artifacts = ["tony/apps/desktop/web/dist/**"]` (dist is gitignored, so hatch would otherwise drop it); `exclude` `node_modules`.
- Flatpak: `sdk-extensions: [org.freedesktop.Sdk.Extension.node20]`, `append-path: /usr/lib/sdk/node20/bin`, npm ci/build before `pip install` (build already has `--share=network`). `finish-args` add `--device=dri` (hardware WebGL for the orb) and `--env=QTWEBENGINE_DISABLE_SANDBOX=1` (Chromium's namespace sandbox cannot start inside bubblewrap with the pip wheel).
- pytest: new marker `web` (loads the built page offscreen), excluded by `addopts` like `voice`.

## Risks / Trade-offs

- [Chromium refuses ES modules over `file://` despite `LocalContentCanAccessFileUrls`] → the `web`-marked smoke test detects it; fallback is D1's custom scheme, which changes only `web_view.py`/`page_policy.py`.
- [CSP with `file:` sources too strict or too loose under an opaque origin] → smoke test asserts the page rendered; the real barrier is `LocalContentCanAccessRemoteUrls=False` + navigation block, CSP is a second layer.
- **Security** [`QTWEBENGINE_DISABLE_SANDBOX=1` in Flatpak removes Chromium's inner renderer sandbox] → only bundled local content runs, remote loads and navigation are blocked, Markdown is escaped + sanitised, and bubblewrap remains the outer sandbox. Outside Flatpak the Chromium sandbox stays on.
- **Security** [`--device=dri` widens the sandbox] → needed for hardware WebGL; without it the orb falls back to the static CSS orb.
- **Security** [any script in the page can call `send`] → page content is only our bundle; the gate validates and refuses `stop`; `unlock` errors never echo the PIN.
- [20 Hz `voice_level` through the core loop and Qt signal] → tiny payloads; only emitted while listening/speaking; React state untouched by them.
- [Chat history lost on renderer crash/reload] → accepted; state-carrying events are replayed.
- [Flatpak build fetches npm packages over the network] → local-build only, same as the existing pip step; lockfile integrity hashes pin them.
- [Removing `markdown-it-py`] → only `presenters/markdown.py` imported it; `uv.lock` and `packaging/requirements.txt` regenerated.

## Migration Plan

1. Land the core (`voice_level`) and Qt-free modules first; the old widgets keep working meanwhile.
2. Land the web front and its tests (not wired).
3. Switch `app.py`/`MainWindow` to the web view and remove widgets/presenters in one commit.
4. Packaging/README last.
Rollback: revert the switch commit (step 3); steps 1–2 are additive.
