"""A stand-in for the Qt WebEngine view: records the page URL and the channel object, so the
default suite never starts a Chromium renderer."""

from PySide6.QtCore import QObject, QUrl
from PySide6.QtWidgets import QWidget


class FakeWebView(QWidget):
    instances: list["FakeWebView"] = []

    def __init__(self, home: QUrl, bridge: QObject) -> None:
        super().__init__()
        self.home = home
        self.channel_objects = {"tony": bridge}
        FakeWebView.instances.append(self)
