import pytest

from tests.fakes.sinks import ListEventSink
from tony.core.guard.policy import Limits
from tony.core.orchestrator.supervisor import TaskSupervisor


def make(**limits):
    sink = ListEventSink()
    return TaskSupervisor(Limits(**limits), sink), sink


class TestSteps:
    def test_thirtieth_step_allowed_thirty_first_cancels(self):
        supervisor, _ = make()

        allowed = [supervisor.step("viernes") for _ in range(30)]

        assert all(allowed) and not supervisor.cancelled.is_set()
        assert supervisor.step("viernes") is False
        assert supervisor.cancelled.is_set()
        assert supervisor.reason == "tarea cancelada: viernes superó el límite de 30 pasos"

    def test_steps_counted_per_agent(self):
        supervisor, _ = make(max_steps_per_agent=2)

        results = [supervisor.step(agent) for agent in ["a", "b", "a", "b"]]

        assert results == [True, True, True, True]
        assert supervisor.step("b") is False
        assert supervisor.reason == "tarea cancelada: b superó el límite de 2 pasos"

    def test_no_step_allowed_after_cancellation(self):
        supervisor, _ = make()
        supervisor.cancel("x")

        assert supervisor.step("viernes") is False


class TestDenials:
    def test_third_denial_of_same_tool_cancels(self):
        supervisor, _ = make()

        supervisor.denied("shell.run", "shell.run/deny")
        supervisor.denied("shell.run", "shell.run/deny")
        assert not supervisor.cancelled.is_set()
        supervisor.denied("shell.run", "shell.run/deny")

        assert supervisor.cancelled.is_set()
        assert supervisor.reason == (
            "tarea cancelada: shell.run bloqueada 3 veces por la política (regla shell.run/deny)"
        )

    def test_denials_of_different_tools_are_independent(self):
        supervisor, _ = make()

        for tool in ["shell.run", "foo.bar", "shell.run", "foo.bar"]:
            supervisor.denied(tool, "default")

        assert not supervisor.cancelled.is_set()

    def test_limit_from_policy(self):
        supervisor, _ = make(max_denied_retries=1)

        supervisor.denied("foo.bar", "default")

        assert supervisor.reason == (
            "tarea cancelada: foo.bar bloqueada 1 veces por la política (regla default)"
        )


class TestUnconfirmed:
    @pytest.mark.parametrize(
        ("user_decision", "reason"),
        [
            (
                "deny",
                "tarea cancelada: el usuario no autorizó filesystem.delete_file "
                "(regla filesystem.delete*/confirm)",
            ),
            (
                "timeout",
                "tarea cancelada: sin respuesta a la confirmación de filesystem.delete_file "
                "en 60 s (regla filesystem.delete*/confirm)",
            ),
        ],
    )
    def test_unconfirmed_call_cancels_with_reason(self, user_decision, reason):
        supervisor, _ = make()

        supervisor.unconfirmed(
            "filesystem.delete_file", "filesystem.delete*/confirm", user_decision
        )

        assert supervisor.cancelled.is_set()
        assert supervisor.reason == reason


class TestCancel:
    def test_keeps_first_reason(self):
        supervisor, _ = make()

        supervisor.cancel("primera")
        supervisor.cancel("segunda")

        assert supervisor.reason == "primera"
        assert supervisor.cancelled.is_set()

    def test_not_cancelled_initially(self):
        supervisor, _ = make()

        assert (supervisor.reason, supervisor.cancelled.is_set()) == (None, False)


class TestTokenAlert:
    def test_one_alert_above_the_limit(self):
        supervisor, sink = make()

        supervisor.record_usage(input_tokens=40000, output_tokens=10000)
        assert sink.events == []
        supervisor.record_usage(input_tokens=1, output_tokens=0)
        supervisor.record_usage(input_tokens=500, output_tokens=500)

        assert sink.events == [{"type": "token_alert", "total_tokens": 50001, "limit": 50000}]
        assert not supervisor.cancelled.is_set()

    def test_no_alert_at_the_limit(self):
        supervisor, sink = make()

        supervisor.record_usage(input_tokens=25000, output_tokens=25000)

        assert sink.events == []

    def test_limit_from_policy(self):
        supervisor, sink = make(token_alert=10)

        supervisor.record_usage(input_tokens=6, output_tokens=5)

        assert sink.events == [{"type": "token_alert", "total_tokens": 11, "limit": 10}]
