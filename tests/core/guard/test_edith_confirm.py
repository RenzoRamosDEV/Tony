import pytest

from tests.core.guard.edith_helpers import audit_lines, call, make_edith
from tests.fakes.confirm import HANG, FakeConfirmer, FakeWording
from tony.core.events.messages import Ruling

DELETE = call("filesystem.delete_file", {"path": "/home/renzo/notas/viejo.md", "token": "abc123"})
RULE = "filesystem.delete*/confirm"
WORDED = f"Acción: borrar /home/renzo/notas/viejo.md. Regla: {RULE}. ¿Autoriza?"


async def test_question_uses_model_wording_from_masked_preview(tmp_path):
    wording = FakeWording(text=WORDED)
    edith, confirmer = make_edith(tmp_path, confirmer=FakeConfirmer([True]), wording=wording)

    await edith.decide(DELETE)

    assert confirmer.questions == [WORDED]
    [(tool, preview, rule)] = wording.inputs
    assert (tool, rule) == ("filesystem.delete_file", RULE)
    assert '"token": "***"' in preview and "abc123" not in preview


async def test_without_wording_model_asks_template(tmp_path):
    edith, confirmer = make_edith(tmp_path, confirmer=FakeConfirmer([True]))

    await edith.decide(DELETE)

    assert confirmer.questions == [
        'Acción: filesystem.delete_file {"path": "/home/renzo/notas/viejo.md", "token": "***"}. '
        f"Regla: {RULE}. ¿Autoriza?"
    ]


@pytest.mark.parametrize(
    ("answer", "user_decision"), [(True, "allow"), (False, "deny"), (None, "deny")]
)
async def test_answer_maps_to_user_decision(tmp_path, answer, user_decision):
    edith, _ = make_edith(tmp_path, confirmer=FakeConfirmer([answer]))

    ruling = await edith.decide(DELETE)

    assert ruling == Ruling(verdict="confirm", rule=RULE, user_decision=user_decision)
    assert audit_lines(tmp_path)[0]["user_decision"] == user_decision


async def test_unanswered_confirmation_times_out(tmp_path):
    edith, confirmer = make_edith(tmp_path, confirmer=FakeConfirmer([HANG]))

    ruling = await edith.decide(DELETE)

    assert ruling == Ruling(verdict="confirm", rule=RULE, user_decision="timeout")
    assert len(confirmer.questions) == 1
    [line] = audit_lines(tmp_path)
    assert (line["verdict"], line["user_decision"]) == ("confirm", "timeout")


async def test_audit_written_after_answer_with_wait_in_duration(tmp_path):
    seen_before_answer = []

    class InspectingConfirmer:
        async def ask(self, question):
            seen_before_answer.append(audit_lines(tmp_path))
            return True

    edith, _ = make_edith(tmp_path, confirmer=InspectingConfirmer(), readings=(100.0, 108.423))

    await edith.decide(DELETE)

    assert seen_before_answer == [[]]
    [line] = audit_lines(tmp_path)
    assert (line["user_decision"], line["duration_ms"]) == ("allow", 8423)


async def test_confirmer_receives_a_masked_json_request(tmp_path):
    from tony.core.guard.confirm import ConfirmationRequest

    edith, confirmer = make_edith(tmp_path, confirmer=FakeConfirmer([True]))

    await edith.decide(DELETE)

    [request] = confirmer.requests
    assert isinstance(request, ConfirmationRequest)
    assert (request.task_id, request.tool) == ("t" * 32, "filesystem.delete_file")
    assert request.args_preview == '{"path": "/home/renzo/notas/viejo.md", "token": "***"}'
    assert request.question == confirmer.questions[0]
    assert ConfirmationRequest.model_validate_json(request.model_dump_json()) == request
