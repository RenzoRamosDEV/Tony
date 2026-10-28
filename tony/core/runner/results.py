"""TaskResults synthesised when the engine does not deliver one (timeout, cancel, error)."""

from __future__ import annotations

from tony.core.runner.cancel import cancellation_error
from tony.core.runner.contracts import TaskResult
from tony.core.runner.proxy import NOT_CONFIRMED, TaskState


def timeout_result(timeout_s: float, steps: list[str]) -> TaskResult:
    return TaskResult(
        status="timeout",
        resumen=f"Tarea interrumpida: superó el límite de {timeout_s:g} s.",
        pasos=list(steps),
        errores=[f"timeout de tarea tras {timeout_s:g} s"],
    )


def error_result(message: str, steps: list[str]) -> TaskResult:
    return TaskResult(
        status="error",
        resumen=f"Error del motor de ejecución: {message}",
        pasos=list(steps),
        errores=[message],
    )


def cancelled_result(state: TaskState) -> TaskResult:
    if state.cancel_reason is not None:
        return TaskResult(
            status="cancelled",
            resumen=f"Tarea cancelada: el usuario no confirmó {state.cancel_reason}.",
            pasos=list(state.steps),
            errores=[NOT_CONFIRMED.format(tool=state.cancel_reason)],
        )
    return external_cancelled_result(state.cancel_token.reason, state.steps)


def external_cancelled_result(reason: str | None, steps: list[str]) -> TaskResult:
    detail = cancellation_error(reason)
    return TaskResult(
        status="cancelled",
        resumen=f"Tarea {detail}.",
        pasos=list(steps),
        errores=[detail],
    )
