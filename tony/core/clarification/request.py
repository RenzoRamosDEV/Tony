from pydantic import BaseModel


class ClarificationRequest(BaseModel):
    request_id: str
    task_id: str
    agent: str
    question: str
    options: list[str] = []
