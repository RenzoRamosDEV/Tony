from pydantic import BaseModel, Field

EXCERPT_MAX_CHARS = 300


class Source(BaseModel):
    """One cited fact: where it came from and the literal text that supports it."""

    connector: str
    id: str
    title: str
    retrieved_at: str
    excerpt: str = Field(max_length=EXCERPT_MAX_CHARS)
