"""Reading, rendering and converting task logs (specs/evals: tony replay)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tony.core.logging.replay import (
    INCOMPLETE_REQUEST,
    ReplayError,
    read_events,
    render_events,
    to_eval,
)

EVENTS = [
    ("task.queued", {"objetivo": "lista los .md", "parent_id": None}),
    ("task.started", {"agent": "viernes", "objetivo": "lista los .md"}),
    ("tool.call", {"tool": "fake.echo", "args": {"text": "hola"}}),
    ("tool.result", {"tool": "fake.echo", "ok": True, "duration_ms": 3, "error": None}),
    ("tool.call", {"tool": "filesystem.list_directory", "args": {"path": "."}}),
    (
        "tool.result",
        {"tool": "filesystem.list_directory", "ok": False, "duration_ms": 1, "error": "roto"},
    ),
    (
        "task.finished",
        {"status": "ok", "usage": {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.01}},
    ),
    (
        "task.result",
        {"result": {"status": "ok", "resumen": "Hecho", "datos": None, "pasos": [], "errores": []}},
    ),
]


def write_log(path: Path, events=EVENTS) -> Path:
    lines = [
        json.dumps(
            {
                "schema_version": 1,
                "ts": "2026-10-28T10:00:00.000Z",
                "task_id": "t1",
                "seq": i,
                "type": t,
                "payload": p,
            }
        )
        for i, (t, p) in enumerate(events, 1)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_read_events_returns_the_parsed_lines(tmp_path: Path) -> None:
    events = read_events(write_log(tmp_path / "t1.jsonl"))

    assert [e["type"] for e in events] == [t for t, _ in EVENTS]
    assert events[2]["payload"]["args"] == {"text": "hola"}


def test_read_events_rejects_missing_file_and_bad_lines(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="no existe"):
        read_events(tmp_path / "nadie.jsonl")

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type": "a"}\n\n{no\n', encoding="utf-8")
    with pytest.raises(ReplayError, match="línea 3"):
        read_events(bad)


def test_render_is_one_readable_line_per_event(tmp_path: Path) -> None:
    text = render_events(read_events(write_log(tmp_path / "t1.jsonl")))

    lines = text.splitlines()
    assert len(lines) == len(EVENTS)
    assert lines[0].startswith("  1 ") and "10:00:00" in lines[0] and "task.queued" in lines[0]
    assert "fake.echo" in lines[2] and "hola" in lines[2]
    assert "ok" in lines[3] and "3 ms" in lines[3]
    assert "error" in lines[5] and "roto" in lines[5]
    assert "10/5" in lines[6] and "0.01" in lines[6]
    assert "status: ok" in lines[7] and "Hecho" in lines[7]


def test_to_eval_derives_the_entry_and_the_fixture_lines(tmp_path: Path) -> None:
    events = read_events(write_log(tmp_path / "t1.jsonl"))

    entry, lines, _ = to_eval(events, "fs-list-md")

    data = yaml.safe_load(entry)
    assert data == [
        {
            "id": "fs-list-md",
            "agent": "viernes",
            "objetivo": "lista los .md",
            "contexto": "",
            "restricciones": [],
            "expect": {
                "status": "ok",
                "tools_called_all": ["fake.echo", "filesystem.list_directory"],
            },
        }
    ]
    assert [json.loads(line)["type"] for line in lines] == [t for t, _ in EVENTS]


def test_to_eval_without_result_or_start_fails(tmp_path: Path) -> None:
    events = read_events(write_log(tmp_path / "t1.jsonl", EVENTS[:-1]))

    with pytest.raises(ReplayError, match="task.result"):
        to_eval(events, "x")
    with pytest.raises(ReplayError, match="task.started"):
        to_eval(read_events(write_log(tmp_path / "t2.jsonl", EVENTS[2:])), "x")


# --- golden rendering and exact conversion -----------------------------------------------------

GOLDEN_RENDER = """\
  1 10:00:00 task.queued {"objetivo": "lista los .md", "parent_id": null}
  2 10:00:00 task.started {"agent": "viernes", "objetivo": "lista los .md"}
  3 10:00:00 tool.call fake.echo {"text": "hola"}
  4 10:00:00 tool.result fake.echo ok (3 ms)
  5 10:00:00 tool.call filesystem.list_directory {"path": "."}
  6 10:00:00 tool.result filesystem.list_directory error: roto (1 ms)
  7 10:00:00 task.finished status=ok tokens 10/5 coste $0.01
  8 10:00:00 task.result status: ok — Hecho"""

GOLDEN_ENTRY = """\
- id: fs-list-md
  agent: viernes
  objetivo: lista los .md
  contexto: ''
  restricciones: []
  expect:
    status: ok
    tools_called_all:
    - fake.echo
    - filesystem.list_directory
"""


def test_render_matches_the_golden_text(tmp_path: Path) -> None:
    assert render_events(read_events(write_log(tmp_path / "t1.jsonl"))) == GOLDEN_RENDER


def test_render_of_text_running_and_bare_events(tmp_path: Path) -> None:
    events = [
        ("task.running", {}),
        ("assistant.text", {"text": "voy\na " + "x" * 200}),
        ("mcp.status", {"fs": {"state": "ready"}}),
    ]

    lines = render_events(read_events(write_log(tmp_path / "t.jsonl", events))).splitlines()

    assert lines[0] == "  1 10:00:00 task.running"
    assert lines[1] == "  2 10:00:00 assistant.text " + ("voy a " + "x" * 200)[:120]
    assert lines[2] == '  3 10:00:00 mcp.status {"fs": {"state": "ready"}}'
    assert render_events([]) == ""


def test_to_eval_entry_matches_the_golden_yaml(tmp_path: Path) -> None:
    entry, lines, _ = to_eval(read_events(write_log(tmp_path / "t1.jsonl")), "fs-list-md")

    assert entry == GOLDEN_ENTRY
    assert lines[0] == json.dumps(
        read_events(write_log(tmp_path / "t2.jsonl"))[0], ensure_ascii=False
    )


def test_to_eval_takes_context_and_restrictions_from_task_started(tmp_path: Path) -> None:
    events = [
        ("task.started", {"agent": "v", "objetivo": "o", "contexto": "c", "restricciones": ["r"]}),
        ("task.result", {"result": {"status": "partial", "resumen": "x"}}),
    ]

    entry, _, _ = to_eval(read_events(write_log(tmp_path / "t.jsonl", events)), "e")

    assert yaml.safe_load(entry) == [
        {
            "id": "e",
            "agent": "v",
            "objetivo": "o",
            "contexto": "c",
            "restricciones": ["r"],
            "expect": {"status": "partial", "tools_called_all": []},
        }
    ]


def test_read_events_rejects_a_non_object_line(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text("[1]\n", encoding="utf-8")

    with pytest.raises(ReplayError, match="línea 1 no es un objeto"):
        read_events(path)


def test_render_uses_sorted_json_defaults_and_placeholders(tmp_path: Path) -> None:
    raw = [
        {"type": "tool.call", "payload": {"tool": "t", "args": {"b": 1, "a": 2}}},
        {"seq": 2, "ts": "2026-10-28T10:00:00.000Z", "type": "task.finished", "payload": {}},
        {"seq": 3, "ts": "x", "type": "assistant.text", "payload": {}},
        {"seq": 4, "ts": "x", "payload": {"k": "v"}},
        {"seq": 5, "ts": "x", "type": "tool.call", "payload": {"tool": "t"}},
    ]
    path = tmp_path / "raw.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in raw) + "\n", encoding="utf-8")

    lines = render_events(read_events(path)).splitlines()

    assert lines[0] == '  ?  tool.call t {"a": 2, "b": 1}'
    assert lines[1] == "  2 10:00:00 task.finished status=None tokens 0/0 coste $0"
    assert lines[2] == "  3  assistant.text"
    assert lines[3] == '  4  ? {"k": "v"}'
    assert lines[4] == "  5  tool.call t {}"


def test_to_eval_prefers_the_queued_objetivo_and_keeps_unicode(tmp_path: Path) -> None:
    events = [
        ("task.queued", {"objetivo": "añade ñ", "parent_id": None}),
        ("task.started", {"agent": "v", "objetivo": "otro"}),
        ("task.result", {"result": {"status": "ok", "resumen": "x"}}),
    ]

    entry, lines, _ = to_eval(read_events(write_log(tmp_path / "t.jsonl", events)), "e")

    assert "objetivo: añade ñ\n" in entry
    assert "añade ñ" in lines[0] and "\\u00f1" not in lines[0]


# --- the full request travels in task.started (review of change 03) ---------------------------


def test_to_eval_warns_when_the_log_lacks_context_and_restrictions(tmp_path: Path) -> None:
    _, _, warnings = to_eval(read_events(write_log(tmp_path / "t.jsonl")), "e")

    assert warnings == [
        "petición incompleta en el registro: task.started no incluye contexto ni "
        "restricciones; revisa la entrada generada"
    ]


def test_to_eval_does_not_warn_when_task_started_carries_the_request(tmp_path: Path) -> None:
    events = [
        ("task.started", {"agent": "v", "objetivo": "o", "contexto": "", "restricciones": []}),
        ("task.result", {"result": {"status": "ok", "resumen": "x"}}),
    ]

    entry, _, warnings = to_eval(read_events(write_log(tmp_path / "t.jsonl", events)), "e")

    assert warnings == []
    assert yaml.safe_load(entry)[0]["contexto"] == ""


def test_to_eval_warns_when_only_one_of_context_or_restrictions_is_logged(tmp_path: Path) -> None:
    events = [
        ("task.started", {"agent": "v", "objetivo": "o", "contexto": "c"}),
        ("task.result", {"result": {"status": "ok", "resumen": "x"}}),
    ]

    _, _, warnings = to_eval(read_events(write_log(tmp_path / "t.jsonl", events)), "e")

    assert warnings == [INCOMPLETE_REQUEST]
