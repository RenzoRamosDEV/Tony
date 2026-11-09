from collections.abc import Callable
from typing import Any

from tony.core.config.placeholders import SecretMasker
from tony.core.guard.audit import ELLIPSIS, canonical_json, mask_args

PREVIEW_FIELD_LIMIT = 2000
Preview = dict[str, str | int]

_EMAIL = ("to", "cc", "subject", "body")
_EVENT = ("summary", "start", "end", "attendees")
_FIELDS_BY_TOOL: dict[str, tuple[str, ...]] = {
    "gmail.send_email": _EMAIL,
    "gmail.draft_email": _EMAIL,
    "filesystem.write_file": ("path", "bytes", "content"),
    "google-calendar.create-event": _EVENT,
    "google-calendar.update-event": _EVENT,
}


def _utf8_size(args: dict[str, Any]) -> int | None:
    content = args.get("content")
    return len(content.encode()) if isinstance(content, str) else None


_DERIVED_FIELDS: dict[str, Callable[[dict[str, Any]], int | None]] = {"bytes": _utf8_size}


def build_preview(tool: str, args: dict[str, Any], masker: SecretMasker) -> Preview:
    """Masked, capped fields the user decides on; the content shown is what will run."""
    fields = _FIELDS_BY_TOOL.get(tool)
    if fields is None:
        return {"args": _capped(canonical_json(mask_args(args, masker)))}
    masked = mask_args(args, masker)
    preview: Preview = {}
    for name in fields:
        if name in _DERIVED_FIELDS:
            size = _DERIVED_FIELDS[name](args)
            if size is not None:
                preview[name] = size
        elif name in masked:
            preview[name] = _capped(_as_text(masked[name]))
    return preview


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else canonical_json(value)


def _capped(text: str) -> str:
    if len(text) > PREVIEW_FIELD_LIMIT:
        return text[:PREVIEW_FIELD_LIMIT] + ELLIPSIS
    return text
