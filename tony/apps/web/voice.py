"""What the web server knows about voice: availability, the engine registry and the executor."""

from __future__ import annotations

from dataclasses import dataclass, field

from tony.core.config import VoiceSettings
from tony.core.voice.engines import (
    EXTRA_HINT,
    EngineRegistry,
    VoiceAvailability,
    voice_availability,
)
from tony.core.voice.executor import VoiceExecutor


@dataclass
class VoiceRuntime:
    availability: VoiceAvailability
    registry: EngineRegistry | None
    executor: VoiceExecutor = field(default_factory=VoiceExecutor)

    @property
    def available(self) -> bool:
        return self.availability.available and self.registry is not None

    @classmethod
    def disabled(cls, settings: VoiceSettings, reason: str | None = None) -> VoiceRuntime:
        reason = reason or f"extra tony[voice] no instalado: {EXTRA_HINT}"
        return cls(VoiceAvailability(False, reason, settings.stt, settings.tts), None)

    @classmethod
    def detect(cls, settings: VoiceSettings) -> VoiceRuntime:
        """Decide once at startup without loading any model."""
        availability = voice_availability(settings)
        registry = EngineRegistry(settings) if availability.available else None
        return cls(availability, registry)

    def close(self) -> None:
        self.executor.close()
