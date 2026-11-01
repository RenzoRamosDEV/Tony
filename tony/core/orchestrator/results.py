from pydantic import ValidationError

from tony.core.events.messages import TaskResult
from tony.core.orchestrator.ports import EngineOutcome

UNSTRUCTURED = "respuesta no estructurada"


def to_task_result(outcome: EngineOutcome) -> TaskResult:
    try:
        return TaskResult.model_validate(outcome.structured)
    except ValidationError:
        return TaskResult(resumen=outcome.text, errores=[UNSTRUCTURED])
