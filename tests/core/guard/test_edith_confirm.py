import uuid
from datetime import timedelta

import pytest

from tests.core.guard.edith_helpers import NOW, MutablePolicySource, audit_lines, call, make_edith
from tests.fakes.confirm import HANG, FakeConfirmer, FakeWording
from tony.core.events.messages import Ruling
from tony.core.guard.audit import args_hash
from tony.core.guard.policy import Policy

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


class SwappingConfirmer:
    """Confirmer that answers yes after swapping the policy source, as a file edit would."""

    def __init__(self, source, swaps):
        self._source = source
        self._swaps = list(swaps)
        self.requests = []

    async def ask(self, request):
        self.requests.append(request)
        if self._swaps:
            self._source.swap(*self._swaps.pop(0))
        return True


def policy_with(delete_verdict, timeout=0.2):
    return Policy.model_validate(
        {
            "default": "deny",
            "rules": [
                {"match": "filesystem.delete*", "verdict": delete_verdict, "id": "delete-rule"}
            ],
            "limits": {"confirm_timeout_s": timeout},
        }
    )


async def test_request_carries_the_approval_binding(tmp_path):
    edith, confirmer = make_edith(tmp_path, confirmer=FakeConfirmer([True]))

    await edith.decide(DELETE)

    [request] = confirmer.requests
    assert uuid.UUID(request.approval_id).version == 4
    assert request.args_digest == args_hash(DELETE.args)
    assert request.policy_version == "v1"
    assert request.expires_at == NOW + timedelta(seconds=0.2)
    assert request.preview == {"args": '{"path": "/home/renzo/notas/viejo.md", "token": "***"}'}


async def test_each_request_gets_a_fresh_approval_id(tmp_path):
    edith, confirmer = make_edith(
        tmp_path, confirmer=FakeConfirmer([True, True]), readings=(1.0,) * 4
    )

    await edith.decide(DELETE)
    await edith.decide(DELETE)

    assert confirmer.requests[0].approval_id != confirmer.requests[1].approval_id


async def test_audit_line_carries_the_asked_approval_id(tmp_path):
    edith, confirmer = make_edith(tmp_path, confirmer=FakeConfirmer([True]))

    await edith.decide(DELETE)

    [line] = audit_lines(tmp_path)
    assert line["approval_id"] == confirmer.requests[0].approval_id


async def test_allow_and_deny_audit_lines_have_no_approval_id(tmp_path):
    edith, _ = make_edith(tmp_path, readings=(1.0,) * 4)

    await edith.decide(call("filesystem.read_file"))
    await edith.decide(call("shell.run"))

    assert [("approval_id" in line) for line in audit_lines(tmp_path)] == [False, False]


async def test_policy_swapped_to_deny_during_the_ask_denies_with_the_new_rule(tmp_path):
    source = MutablePolicySource(policy_with("confirm"))
    confirmer = SwappingConfirmer(source, [(policy_with("deny"), "v2")])
    edith, _ = make_edith(tmp_path, source=source, confirmer=confirmer)

    ruling = await edith.decide(DELETE)

    assert ruling == Ruling(verdict="deny", rule="delete-rule", user_decision=None)
    assert len(confirmer.requests) == 1
    [line] = audit_lines(tmp_path)
    assert (line["verdict"], line["rule"], "approval_id" in line) == ("deny", "delete-rule", False)


async def test_policy_swapped_to_allow_during_the_ask_allows_without_asking_again(tmp_path):
    source = MutablePolicySource(policy_with("confirm"))
    confirmer = SwappingConfirmer(source, [(policy_with("allow"), "v2")])
    edith, _ = make_edith(tmp_path, source=source, confirmer=confirmer)

    ruling = await edith.decide(DELETE)

    assert (ruling.verdict, ruling.rule, ruling.user_decision) == ("allow", "delete-rule", None)
    assert len(confirmer.requests) == 1


async def test_policy_changed_but_still_confirm_asks_again_with_a_new_approval(tmp_path):
    source = MutablePolicySource(policy_with("confirm"))
    confirmer = SwappingConfirmer(source, [(policy_with("confirm"), "v2")])
    edith, _ = make_edith(tmp_path, source=source, confirmer=confirmer)

    ruling = await edith.decide(DELETE)

    first, second = confirmer.requests
    assert (first.policy_version, second.policy_version) == ("v1", "v2")
    assert first.approval_id != second.approval_id
    assert (ruling.verdict, ruling.user_decision) == ("confirm", "allow")
    [line] = audit_lines(tmp_path)
    assert line["approval_id"] == second.approval_id


async def test_policy_changing_on_every_ask_is_denied_after_three_requests(tmp_path):
    source = MutablePolicySource(policy_with("confirm"))
    swaps = [(policy_with("confirm"), f"v{n}") for n in (2, 3, 4)]
    confirmer = SwappingConfirmer(source, swaps)
    edith, _ = make_edith(tmp_path, source=source, confirmer=confirmer)

    ruling = await edith.decide(DELETE)

    assert len(confirmer.requests) == 3
    assert (ruling.verdict, ruling.rule, ruling.user_decision) == (
        "confirm",
        "delete-rule",
        "deny",
    )
    [line] = audit_lines(tmp_path)
    assert line["approval_id"] == confirmer.requests[2].approval_id


async def test_two_changes_then_a_stable_policy_is_allowed(tmp_path):
    source = MutablePolicySource(policy_with("confirm"))
    swaps = [(policy_with("confirm"), "v2"), (policy_with("confirm"), "v3")]
    confirmer = SwappingConfirmer(source, swaps)
    edith, _ = make_edith(tmp_path, source=source, confirmer=confirmer)

    ruling = await edith.decide(DELETE)

    assert len(confirmer.requests) == 3
    assert ruling.user_decision == "allow"


async def test_a_no_answer_is_not_re_evaluated_even_if_the_policy_changed(tmp_path):
    source = MutablePolicySource(policy_with("confirm"))

    class DenyingConfirmer(SwappingConfirmer):
        async def ask(self, request):
            await super().ask(request)
            return False

    confirmer = DenyingConfirmer(source, [(policy_with("allow"), "v2")])
    edith, _ = make_edith(tmp_path, source=source, confirmer=confirmer)

    ruling = await edith.decide(DELETE)

    assert (ruling.verdict, ruling.user_decision) == ("confirm", "deny")
    assert len(confirmer.requests) == 1


async def test_request_preview_is_typed_for_known_tools(tmp_path):
    policy = Policy.model_validate({"default": "confirm"})
    edith, confirmer = make_edith(tmp_path, confirmer=FakeConfirmer([True]), policy=policy)

    await edith.decide(call("filesystem.write_file", {"path": "/a.md", "content": "hola"}))

    assert confirmer.requests[0].preview == {"path": "/a.md", "bytes": 4, "content": "hola"}
