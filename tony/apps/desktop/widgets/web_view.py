from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QFile, QIODevice, QObject, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEnginePermission,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from tony.apps.desktop.page_policy import navigation_decision

CHANNEL_SCRIPT = "qwebchannel.js"
_CHANNEL_RESOURCE = ":/qtwebchannel/qwebchannel.js"
_Attribute = QWebEngineSettings.WebAttribute


def _channel_script() -> QWebEngineScript:
    resource = QFile(_CHANNEL_RESOURCE)
    resource.open(QIODevice.OpenModeFlag.ReadOnly)
    script = QWebEngineScript()
    script.setName(CHANNEL_SCRIPT)
    script.setSourceCode(bytes(resource.readAll().data()).decode("utf-8"))
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    return script


class TonyPage(QWebEnginePage):
    """The local page on Qt 6's off-the-record default profile: it stays on `home`, hands
    `http`/`https` link clicks to `open_external` and gets every permission denied."""

    def __init__(
        self,
        home: QUrl,
        *,
        open_external: Callable[[QUrl], Any] = QDesktopServices.openUrl,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(QWebEngineProfile.defaultProfile(), parent)
        self._home = home
        self._open_external = open_external
        settings = self.settings()
        settings.setAttribute(_Attribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(_Attribute.LocalContentCanAccessRemoteUrls, False)
        self.scripts().insert(_channel_script())
        self.permissionRequested.connect(self.deny_permission)

    @staticmethod
    def deny_permission(permission: QWebEnginePermission) -> None:
        permission.deny()

    def acceptNavigationRequest(
        self, url: QUrl | str, type: QWebEnginePage.NavigationType, isMainFrame: bool
    ) -> bool:
        url = QUrl(url)
        link_click = type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
        decision = navigation_decision(url.toString(), self._home.toString(), link_click=link_click)
        if decision == "external":
            self._open_external(url)
        return decision == "allow"

    def createWindow(self, type: QWebEnginePage.WebWindowType) -> None:
        return None


def create_web_view(home: QUrl, bridge: QObject, controls: QObject | None = None) -> QWebEngineView:
    """A view on a `TonyPage` with `bridge` registered as `tony` and, if given, `controls`
    registered as `windowControls`; the caller loads `home`."""
    view = QWebEngineView()
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    page = TonyPage(home, parent=view)
    channel = QWebChannel(page)
    channel.registerObject("tony", bridge)
    if controls is not None:
        channel.registerObject("windowControls", controls)
    page.setWebChannel(channel)
    view.setPage(page)
    return view
