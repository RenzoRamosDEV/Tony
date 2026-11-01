import json
from typing import get_args

import pytest
from pydantic import ValidationError

from tony.core.events.messages import Decision, Ruling, TaskRequest, TaskResult, ToolCall


class TestTaskRequest:
    def test_defaults_context_and_restrictions(self):
        request = TaskRequest(objetivo="Lista mis notas")

        assert request.model_dump() == {
            "objetivo": "Lista mis notas",
            "contexto": "",
            "restricciones": [],
        }

    @pytest.mark.parametrize("objetivo", ["", " ", "\n\t "])
    def test_rejects_blank_objective(self, objetivo):
        with pytest.raises(ValidationError, match="objetivo"):
            TaskRequest(objetivo=objetivo)

    def test_accepts_single_character_objective(self):
        assert TaskRequest(objetivo="x").objetivo == "x"

    def test_round_trips_through_json(self):
        request = TaskRequest(objetivo="o", contexto="c", restricciones=["r1", "r2"])

        assert TaskRequest.model_validate_json(request.model_dump_json()) == request

    def test_rejects_non_string_restriction(self):
        with pytest.raises(ValidationError, match="restricciones"):
            TaskRequest(objetivo="o", restricciones=[{"x": 1}])


class TestTaskResult:
    def test_exposes_exactly_the_contract_keys(self):
        result = TaskResult(resumen="hecho", datos={"n": 1}, pasos=["a"], errores=[])

        assert json.loads(result.model_dump_json()) == {
            "resumen": "hecho",
            "datos": {"n": 1},
            "pasos": ["a"],
            "errores": [],
        }

    def test_defaults_to_null_data_and_empty_lists(self):
        result = TaskResult(resumen="r")

        assert (result.datos, result.pasos, result.errores) == (None, [], [])

    @pytest.mark.parametrize("datos", [None, 3, "texto", [1, "a"], {"k": [1]}])
    def test_datos_accepts_any_json_value(self, datos):
        result = TaskResult(resumen="r", datos=datos)

        assert TaskResult.model_validate_json(result.model_dump_json()).datos == datos

    def test_requires_resumen(self):
        with pytest.raises(ValidationError, match="resumen"):
            TaskResult.model_validate({"datos": None, "pasos": [], "errores": []})


class TestToolCall:
    ENVELOPE = {
        "task_id": "abc",
        "agent": "viernes",
        "tool": "filesystem.read_file",
        "args": {"path": "a.md"},
    }

    def test_round_trips_through_json_unchanged(self):
        call = ToolCall.model_validate(self.ENVELOPE)

        assert json.loads(call.model_dump_json()) == self.ENVELOPE
        assert ToolCall.model_validate_json(call.model_dump_json()) == call

    @pytest.mark.parametrize("missing", ["task_id", "agent", "tool", "args"])
    def test_requires_every_envelope_field(self, missing):
        data = {k: v for k, v in self.ENVELOPE.items() if k != missing}

        with pytest.raises(ValidationError, match=missing):
            ToolCall.model_validate(data)


def test_decision_literal_values():
    assert set(get_args(Decision)) == {"allow", "confirm", "deny"}


class TestRuling:
    @pytest.mark.parametrize("user_decision", ["allow", "deny", "timeout", None])
    def test_json_round_trip(self, user_decision):
        ruling = Ruling(verdict="confirm", rule="r/confirm", user_decision=user_decision)

        assert Ruling.model_validate_json(ruling.model_dump_json()) == ruling

    def test_user_decision_defaults_to_none(self):
        ruling = Ruling(verdict="allow", rule="a/allow")

        assert ruling.model_dump(mode="json") == {
            "verdict": "allow",
            "rule": "a/allow",
            "user_decision": None,
        }

    @pytest.mark.parametrize("user_decision", ["confirm", "yes", ""])
    def test_invalid_user_decision_rejected(self, user_decision):
        with pytest.raises(ValidationError, match="user_decision"):
            Ruling(verdict="confirm", rule="r", user_decision=user_decision)

    def test_invalid_verdict_rejected(self):
        with pytest.raises(ValidationError, match="verdict"):
            Ruling(verdict="maybe", rule="r")
