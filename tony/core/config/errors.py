from pydantic import ValidationError


class DefinitionError(Exception):
    def __init__(self, file: str, field: str | None, message: str) -> None:
        self.file = file
        self.field = field
        self.message = message
        location = f"{file}: {field}" if field else file
        super().__init__(f"{location}: {message}")

    @classmethod
    def from_validation(cls, file: str, error: ValidationError) -> "DefinitionError":
        first = error.errors()[0]
        field = ".".join(str(part) for part in first["loc"]) or None
        return cls(file, field, first["msg"])
