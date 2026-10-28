"""GET /api/conversations and /api/conversations/{id}/messages (specs/web-api)."""

from __future__ import annotations

from pathlib import Path

from tests.apps.web.helpers import build_test_app
from tony.core.memory.conversations import ConversationStore


def seed(tmp_path: Path) -> list[str]:
    store = ConversationStore(tmp_path / "memory" / "conversations.sqlite")
    created = [store.start_conversation("cli" if i < 3 else "web") for i in range(25)]
    store.add_message(created[0], "user", "hola", None, message_id="m1")
    store.add_message(created[0], "assistant", "Hola, señor.", "text", message_id="m2")
    store.close()
    return created


def test_list_returns_the_twenty_most_recent_first(tmp_path: Path) -> None:
    created = seed(tmp_path)
    with build_test_app(tmp_path) as client:
        listed = client.get("/api/conversations").json()

    assert len(listed) == 20
    assert listed[0]["id"] == created[-1]
    assert [c["id"] for c in listed] == list(reversed(created))[:20]
    assert set(listed[0]) == {"id", "channel", "created_at"} and listed[0]["channel"] == "web"


def test_messages_of_a_conversation_in_chronological_order(tmp_path: Path) -> None:
    created = seed(tmp_path)
    with build_test_app(tmp_path) as client:
        messages = client.get(f"/api/conversations/{created[0]}/messages").json()

    assert [(m["id"], m["role"], m["content"], m["reply_mode"]) for m in messages] == [
        ("m1", "user", "hola", None),
        ("m2", "assistant", "Hola, señor.", "text"),
    ]
    assert all(m["created_at"] for m in messages)


def test_unknown_conversation_is_404(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        response = client.get("/api/conversations/nope/messages")

    assert response.status_code == 404
    assert (
        response.json()["error"] == "unknown_conversation" and "nope" in response.json()["detail"]
    )
