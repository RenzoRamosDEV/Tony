"""Fake `codex` binary used to test the codex_cli engine (no network, no real Codex).

Emulates the handful of `codex exec`/`codex exec resume --json --output-schema` shapes
the codex_cli engine (group 4) drives: each subprocess invocation consumes the next
response from a JSON script file given via `FAKE_CODEX_SCRIPT`, and `resume <id>` is
validated against the session id the previous response carried.

Run with: python -m tests.fakes.fake_codex exec [resume <session_id>] [--json]
    [--output-schema PATH] [-m MODEL] [-c KEY=VALUE]... PROMPT
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_ENV_VAR = "FAKE_CODEX_SCRIPT"


def write_script(path: Path, responses: list[dict[str, Any]]) -> Path:
    """Test helper: write a script file consumed one response per `fake_codex` invocation."""
    path.write_text(json.dumps({"responses": responses}), encoding="utf-8")
    return path


def _load(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data["responses"])


def _save(path: Path, responses: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"responses": responses}), encoding="utf-8")


def _parse_resume_session(argv: list[str]) -> str | None:
    if len(argv) >= 2 and argv[0] == "exec" and argv[1] == "resume":
        return argv[2] if len(argv) > 2 else None
    return None


def main(argv: list[str]) -> int:
    script_var = os.environ.get(SCRIPT_ENV_VAR)
    if not script_var:
        print(f"fake_codex: falta la variable de entorno {SCRIPT_ENV_VAR}", file=sys.stderr)
        return 2
    script_path = Path(script_var)
    responses = _load(script_path)

    resume_session = _parse_resume_session(argv)
    if resume_session is not None:
        if not responses:
            print("fake_codex: resume sin respuestas restantes en el guion", file=sys.stderr)
            return 1
        expected = responses[0].get("session_id")
        if expected != resume_session:
            print(
                f"fake_codex: resume con session_id '{resume_session}' no coincide "
                f"con la sesión esperada '{expected}'",
                file=sys.stderr,
            )
            return 1

    if not responses:
        print("fake_codex: el guion de respuestas está agotado", file=sys.stderr)
        return 1

    response, rest = responses[0], responses[1:]
    _save(script_path, rest)

    event = {
        "type": "result",
        "session_id": response.get("session_id"),
        "result": response.get("result"),
    }
    print(json.dumps(event))
    return int(response.get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
