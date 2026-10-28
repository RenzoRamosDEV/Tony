"""Effective reply mode per message and the front's structured output contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from tony.core.config import ReplyMode
from tony.core.loader import Style

ResolvedMode = Literal["voice", "text", "both"]
ModeSource = Literal["prefix", "settings", "yaml"]
InputModality = Literal["text", "audio"]

PREFIXES: dict[str, ResolvedMode] = {"/v": "voice", "/t": "text", "/b": "both"}
PREFIX_FOR_MODE: dict[ResolvedMode, str] = {mode: prefix for prefix, mode in PREFIXES.items()}
BOTH_INSTRUCTION = (
    "Produce las dos versiones: `speech_text` como resumen hablado (sin markdown, tablas ni "
    "código) y `display_text` con el contenido completo."
)
NO_STYLE = "(sin indicaciones)"


@dataclass(frozen=True)
class EffectiveMode:
    mode: ResolvedMode
    source: ModeSource


class FrontReply(BaseModel):
    # speech_text goes first: the model fills properties in schema order, so the spoken
    # reply starts streaming (and synthesizing) before the longer display text.
    speech_text: str | None = None
    display_text: str


def strip_prefix(text: str) -> tuple[ResolvedMode | None, str]:
    head, _, rest = text.partition(" ")
    head = head.strip()
    if head in PREFIXES and (rest or text.strip() == head):
        return PREFIXES[head], rest.strip()
    return None, text


def resolve_reply_mode(
    prefix: ResolvedMode | None,
    persisted: ReplyMode | None,
    yaml_default: ReplyMode,
    input_modality: InputModality,
) -> EffectiveMode:
    if prefix is not None:
        return EffectiveMode(prefix, "prefix")
    if persisted is not None:
        return EffectiveMode(_resolve_auto(persisted, input_modality), "settings")
    return EffectiveMode(_resolve_auto(yaml_default, input_modality), "yaml")


def _resolve_auto(mode: ReplyMode, input_modality: InputModality) -> ResolvedMode:
    if mode == "auto":
        return "voice" if input_modality == "audio" else "text"
    return mode


def style_instruction(style: Style, mode: ResolvedMode) -> str:
    if mode == "both":
        return (
            f"Estilo hablado: {style.voice or NO_STYLE}\n"
            f"Estilo escrito: {style.text or NO_STYLE}\n{BOTH_INSTRUCTION}"
        )
    chosen = style.voice if mode == "voice" else style.text
    return f"Estilo: {chosen or NO_STYLE}"


def parse_front_reply(structured: Any, fallback_text: str, mode: ResolvedMode) -> FrontReply:
    try:
        reply = FrontReply.model_validate(structured)
    except ValidationError:
        return FrontReply(display_text=fallback_text, speech_text=None)
    if mode == "text":
        return reply.model_copy(update={"speech_text": None})
    return reply
