# Proposal

## Why

The v2 desktop window is built from plain PySide6 widgets, while the v1 web front (branch `main`, `tony/apps/web/frontend/`) already has the intended look: the three.js orb, the HUD chat panel, the microphone button and the confirmation card. The user wants that look in the desktop app: one native window, no browser and no web server, with audio still handled entirely by the Python core.

## What Changes

- Port the v1 React front (Vite + React 18 + TypeScript + three.js, same pinned versions) to `tony/apps/desktop/web/`: orb (scene, geometry, amplitude, tween, WebGL check, fallback), chat panel, microphone button, confirmation card, Markdown rendering (marked + DOMPurify) and styles. The v1 browser audio, websocket protocol, engine selector and HTTP client are **not** ported.
- Rebuild the v2-only pieces in the same style inside the page: reply-mode selector, collapsible Activity panel, collapsible Edith audit panel and a PIN overlay.
- **BREAKING (UI)**: the main window's central widget becomes a Qt WebEngine view loading the built page from `tony/apps/desktop/web/dist/index.html` through a local file URL. The PySide6 chat, activity, Edith and PIN widgets and the «Desbloquear Edith» menu are removed, together with the presenters only they used (chat, activity, Edith, PIN, voice, Markdown, bundle). The tray presenter and the confirmation-notification logic stay.
- Add a Qt WebChannel bridge: one signal carrying every core event as JSON, one `send` slot for the existing commands (validated by the existing command parser, internal `stop` refused), an `audit_today` slot returning today's audit rows without tool arguments, and a `ready` slot that replays the last state-carrying events (voice state, reply mode, auth, MCP status, pending confirmation) to a freshly loaded page.
- Page sandbox: every permission request (microphone, camera, geolocation, notifications and the rest) is denied, navigation away from the local page is blocked, `http`/`https` links open in the system browser, local content cannot load remote resources, and the page loads no remote fonts.
- Orb state derived from events (`idle`, `listening`, `thinking`, `speaking`, `confirming`) and orb amplitude from one new core event, `voice_level` {source, level}, published about 20 times per second while listening or speaking. Levels are numbers only; audio still never leaves the core.
- Missing build: when `dist/index.html` does not exist the window shows a native message with the build command; tray, voice, single instance, `tony --focus`, hotkey and notifications keep working.
- Build and packaging: `npm --prefix tony/apps/desktop/web ci && npm --prefix tony/apps/desktop/web run build`; `dist/` and `node_modules/` gitignored and the built `dist/` shipped in the wheel; the Flatpak manifest builds the front with the Node SDK extension, and the sandbox gains GPU access for WebGL and the Qt WebEngine sandbox switch it needs inside Flatpak. The now unused `markdown-it-py` dependency is removed.
- Tests: vitest + Testing Library for the page (ported orb golden tests, event reducer, confirmation card, PIN overlay); pytest + pytest-qt offscreen with fakes for the bridge, page policy and missing-build fallback; a `web`-marked test (excluded by default) that loads the built page offscreen.

## Capabilities

### New Capabilities
<!-- None: the web front replaces the desktop window's content, so its requirements live in the existing desktop-app capability. -->

### Modified Capabilities
- `desktop-app`: the window hosts the embedded web front; the three-zone layout, the Edith banner and the PIN dialog are replaced by the page layout, the confirmation card and the PIN overlay; adds the page bridge, page sandbox, orb state and amplitude, missing-build fallback and frontend build; the audit view reads rows through the bridge; the command path from the page is validated and refuses `stop`.
- `desktop-integration`: clicking the confirmation notification reveals the window on the confirmation card (instead of the Edith zone) with focus on «Denegar».
- `core-events`: adds the `voice_level` event.
- `flatpak-packaging`: the manifest builds the web front; the sandbox permissions add `--device=dri` and `--env=QTWEBENGINE_DISABLE_SANDBOX=1`; the documentation covers the frontend build.

## Impact

- Code: `tony/apps/desktop/` (new `web/` front, `page_policy.py`, `page_protocol.py`, `page_bridge.py`, `widgets/web_view.py`, rewritten `widgets/main_window.py` and `app.py` wiring; removed chat/activity/Edith/PIN widgets and presenters), `tony/core/events/core_events.py` (`voice_level`), `tony/core/voice/` (new `levels.py`; level hooks in listener, speaker and service).
- Tests: removed presenter/widget tests; new vitest suite; new bridge/policy/protocol/level tests; `tests/core/orchestrator/test_runner_subagents.py` asserts on events instead of the removed activity presenter.
- Dependencies: Node.js (>= 20) and npm become build-time tools for the desktop front; `markdown-it-py` removed; `PySide6` Qt WebEngine (already installed with `pyside6`) is now used.
- Packaging: `.gitignore`, `pyproject.toml` (wheel artifacts, `web` marker), `uv.lock`, `packaging/requirements.txt`, Flatpak manifest, README.
- Not affected: core behaviour, Edith policy and confirmation semantics, voice engines, `tony chat`/`tony run`, tray, single instance, hotkey.
