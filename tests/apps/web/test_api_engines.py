"""Engine selection uses fake conversations without invoking providers."""

import asyncio
import json

import pytest

from tests.apps.web.helpers import Doubles, FakeSocket
from tests.fakes.conversation import FakeConversationRunner
from tony.apps.web.hub import ConversationHub
from tony.apps.web.options import WebOptions
from tony.apps.web.server import create_app
from tony.core.channels import bootstrap

CONFIG = (
    "engines:\n  coding:\n    type: litellm\n    model: gpt-4o-mini\n"
    "  fast:\n    type: litellm\n    model: gpt-4o\n"
)


@pytest.fixture
async def engines(tmp_path, monkeypatch):
    doubles = Doubles(tmp_path)
    doubles.settings_yaml(CONFIG)
    hub = ConversationHub(doubles.clock)
    runtime = await doubles.build(hub.gate_factory)
    hub.bind(runtime)
    created = []

    def build(settings, spec):
        runner = FakeConversationRunner([{"display_text": "Nuevo motor", "speech_text": None}])
        created.append((spec.engine, runner))
        return lambda settings, gate, call: runner

    monkeypatch.setattr(bootstrap, "build_conversation", build)
    socket = FakeSocket()
    await hub.hello(socket, None, 0)
    try:
        yield hub, runtime, socket, created
    finally:
        await hub.aclose()
        await runtime.aclose()


async def test_switch_starts_new_conversation_and_persists(engines):
    hub, runtime, socket, created = engines
    previous = hub.conversation_id
    await hub.change_engine("coding")
    assert runtime.front.engine == "coding"
    assert runtime.front_runner is created[0][1]
    assert created[0][0] == "coding"
    assert hub.conversation_id != previous
    assert runtime.memory.conversations.has_conversation(previous)
    assert socket.last("hello.ok")["conversation_id"] == hub.conversation_id
    assert (
        json.loads((runtime.options.config_path.parent / "engine-auth.json").read_text())["active"]
        == "coding"
    )
    assert runtime.settings.selected_engine == "coding"
    await hub.user_text("Hola")
    await hub.turn
    assert runtime.memory.conversations.messages(hub.conversation_id)[-1].content == "Nuevo motor"


@pytest.mark.parametrize("reason", ["unknown", "turn", "task"])
async def test_invalid_or_busy_switch_preserves_everything(engines, reason):
    hub, runtime, socket, created = engines
    previous = hub.conversation_id
    path = runtime.front.path / "agent.md"
    before = path.read_bytes()
    if reason == "turn":
        hub.turn = asyncio.create_task(asyncio.Event().wait())
    elif reason == "task":
        runtime.session.active_task_ids.add("busy")
    try:
        with pytest.raises(ValueError):
            await hub.change_engine("missing" if reason == "unknown" else "coding")
        assert runtime.front.engine == "claude_sdk"
        assert hub.conversation_id == previous
        assert path.read_bytes() == before
        assert created == []
    finally:
        runtime.session.active_task_ids.clear()
        if hub.turn is not None:
            hub.turn.cancel()
            await asyncio.gather(hub.turn, return_exceptions=True)


async def test_failed_open_restores_previous_engine_and_file(engines, monkeypatch):
    hub, runtime, socket, created = engines
    previous = hub.conversation_id
    before = (runtime.front.path / "agent.md").read_bytes()

    class BrokenRunner(FakeConversationRunner):
        async def open(self, *args, **kwargs):
            raise RuntimeError("cannot open")

    monkeypatch.setattr(
        bootstrap, "build_conversation", lambda *args: lambda *args: BrokenRunner([])
    )
    with pytest.raises(ValueError, match="No se pudo cambiar"):
        await hub.change_engine("coding")
    assert runtime.front.engine == "claude_sdk"
    assert hub.conversation_id == previous
    assert (runtime.front.path / "agent.md").read_bytes() == before
    assert socket.last("hello.ok")["conversation_id"] == previous


async def test_engine_api_lists_profiles_and_rejects_unknown(engines):
    import httpx

    hub, runtime, socket, created = engines

    async def boot():
        return hub, runtime

    app = create_app(boot, WebOptions("127.0.0.1", 8787, runtime.options))
    app.state.hub, app.state.runtime = hub, runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Origin": "http://127.0.0.1:8787"},
    ) as client:
        result = await client.get("/api/engines")
        assert result.status_code == 200
        view = result.json()
        assert view["active"] == "claude_sdk"
        assert {p["name"]: p["type"] for p in view["profiles"]} == {
            "claude_sdk": "claude_sdk",
            "coding": "litellm",
            "fast": "litellm",
            "claude-account": "claude_sdk",
            "openai-api": "litellm",
            "anthropic-api": "litellm",
        }
        rejected = await client.patch("/api/engines", json={"profile": "missing"})
        assert rejected.status_code == 400
        assert "missing" in rejected.json()["detail"]
        changed = await client.patch("/api/engines", json={"profile": "fast"})
        assert changed.status_code == 200
        assert changed.json()["active"] == "fast"


async def test_failed_save_restores_previous_session(engines, monkeypatch):
    from tony.apps.web import hub as hub_module

    hub, runtime, socket, created = engines
    previous = hub.conversation_id
    before = (runtime.front.path / "agent.md").read_bytes()

    def fail(*args):
        raise OSError("read only")

    monkeypatch.setattr(hub_module, "save_engine_auth", fail)
    with pytest.raises(ValueError, match="No se pudo cambiar"):
        await hub.change_engine("coding")
    assert runtime.front.engine == "claude_sdk"
    assert hub.conversation_id == previous
    assert created[0][1].closed
    assert (runtime.front.path / "agent.md").read_bytes() == before


async def test_selecting_active_profile_does_not_reset_conversation(engines):
    hub, runtime, socket, created = engines
    previous = hub.conversation_id
    await hub.change_engine("claude_sdk")
    assert hub.conversation_id == previous
    assert created == []


async def test_api_credentials_are_private_persisted_and_required_before_switch(engines):
    from types import SimpleNamespace

    from pydantic import SecretStr

    from tony.apps.web.api import get_engines
    from tony.core.config import TonySettings
    from tony.core.config.engine_auth import load_engine_auth

    hub, runtime, _, _ = engines
    with pytest.raises(ValueError, match="API key"):
        await hub.change_engine("openai-api")
    await hub.configure_engine("openai-api", "gpt-4o", SecretStr("private-test-key"), False)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=runtime)))
    view = await get_engines(request)
    assert "private-test-key" not in json.dumps(view)
    assert next(p for p in view["profiles"] if p["name"] == "openai-api")["configured"]
    await hub.change_engine("openai-api")
    assert runtime.front.engine == runtime.settings.selected_engine == "openai-api"
    restored = TonySettings()
    load_engine_auth(restored, runtime.options.config_path.parent / "engine-auth.json")
    assert restored.selected_engine == "openai-api"
    assert restored.engines["openai-api"].api_key.get_secret_value() == "private-test-key"
    with pytest.raises(ValueError, match="otro motor"):
        await hub.configure_engine("openai-api", "gpt-4o", None, True)
    await hub.change_engine("coding")
    await hub.configure_engine("openai-api", "gpt-4o", None, True)
    with pytest.raises(ValueError, match="API key"):
        await hub.change_engine("openai-api")


async def test_credentials_failed_save_restores_old_key_and_model(engines, monkeypatch):
    from pydantic import SecretStr

    from tony.apps.web import hub as module

    hub, runtime, _, _ = engines
    await hub.configure_engine("openai-api", "gpt-4o", SecretStr("old-private-key"), False)
    path = runtime.options.config_path.parent / "engine-auth.json"
    before = path.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(module, "save_engine_auth", fail)
    with pytest.raises(ValueError, match="guardar"):
        await hub.configure_engine(
            "openai-api", "different-model", SecretStr("new-private-key"), False
        )
    assert runtime.settings.engines["openai-api"].api_key.get_secret_value() == "old-private-key"
    assert runtime.settings.engines["openai-api"].model == "openai/gpt-4o"
    assert path.read_bytes() == before


async def test_background_task_blocks_engine_switch(engines):
    from tony.core.runner import TaskRequest

    hub, runtime, _, _ = engines
    runtime.orchestrator.submit(TaskRequest(objetivo="queued work"))
    with pytest.raises(ValueError, match="termine"):
        await hub.change_engine("coding")


async def test_credentials_endpoint_never_returns_secrets_and_enforces_origin(engines):
    import httpx

    hub, runtime, _, _ = engines

    async def boot():
        return hub, runtime

    app = create_app(boot, WebOptions("127.0.0.1", 8787, runtime.options))
    app.state.hub, app.state.runtime = hub, runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = {"model": "gpt-4o", "api_key": "private-test-key"}
        blocked = await client.put("/api/engines/openai-api/credentials", json=body)
        assert blocked.status_code == 403
        assert runtime.settings.engines["openai-api"].api_key is None
        headers = {"Origin": "http://127.0.0.1:8787"}
        saved = await client.put("/api/engines/openai-api/credentials", json=body, headers=headers)
        assert saved.status_code == 200
        assert "private-test-key" not in saved.text
        read = await client.get("/api/engines")
        assert "private-test-key" not in read.text
        invalid = await client.put(
            "/api/engines/openai-api/credentials",
            json={**body, "model": "anthropic/wrong"},
            headers=headers,
        )
        assert invalid.status_code == 400
        assert "private-test-key" not in invalid.text
    log = runtime.worker_factory.open_log("credential-redaction")
    log.emit("provider.error", {"detail": "private-test-key"})
    log.close()
    assert "private-test-key" not in log.path.read_text()
