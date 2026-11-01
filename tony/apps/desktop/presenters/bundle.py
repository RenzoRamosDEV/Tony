import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tony.apps.desktop.presenters.activity import ActivityPresenter
from tony.apps.desktop.presenters.chat import ChatPresenter, Submit
from tony.apps.desktop.presenters.edith import EdithPresenter
from tony.apps.desktop.presenters.pin import PinPresenter
from tony.apps.desktop.presenters.tray import TrayPresenter
from tony.apps.desktop.presenters.voice import VoicePresenter
from tony.core.events.core_events import Event


@dataclass(frozen=True)
class Presenters:
    chat: ChatPresenter
    activity: ActivityPresenter
    edith: EdithPresenter
    pin: PinPresenter
    voice: VoicePresenter
    tray: TrayPresenter

    @classmethod
    def create(
        cls,
        submit: Submit,
        root: Path,
        *,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> "Presenters":
        return cls(
            chat=ChatPresenter(submit),
            activity=ActivityPresenter(),
            edith=EdithPresenter(submit, root, now=now),
            pin=PinPresenter(submit, monotonic=monotonic),
            voice=VoicePresenter(submit),
            tray=TrayPresenter(),
        )

    def apply(self, event: Event) -> None:
        for presenter in (
            self.chat,
            self.activity,
            self.edith,
            self.pin,
            self.voice,
            self.tray,
        ):
            presenter.apply(event)
