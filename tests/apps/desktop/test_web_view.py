import pytest
import shiboken6
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEnginePermission,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)

from tony.apps.desktop.page_bridge import PageBridge
from tony.apps.desktop.widgets.web_view import CHANNEL_SCRIPT, TonyPage, create_web_view

HOME = QUrl("file:///x/dist/index.html")
LINK = QWebEnginePage.NavigationType.NavigationTypeLinkClicked
TYPED = QWebEnginePage.NavigationType.NavigationTypeTyped
Permission = QWebEnginePermission.PermissionType


@pytest.fixture
def page(qapp):
    opened = []
    page = TonyPage(HOME, open_external=opened.append)
    yield page, opened
    shiboken6.delete(page)


@pytest.mark.parametrize("url", [HOME, QUrl("file:///x/dist/index.html#chat")])
def test_home_navigation_is_accepted(page, url):
    tony_page, opened = page
    assert tony_page.acceptNavigationRequest(url, TYPED, True) is True
    assert opened == []


def test_http_link_click_opens_externally_and_stays(page):
    tony_page, opened = page
    url = QUrl("https://example.org/")
    assert tony_page.acceptNavigationRequest(url, LINK, True) is False
    assert opened == [url]


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("file:///etc/passwd", LINK),
        ("javascript:alert(1)", LINK),
        ("mailto:a@b.c", LINK),
        ("https://example.org/", TYPED),
    ],
)
def test_other_navigation_is_blocked_without_opening_anything(page, url, kind):
    tony_page, opened = page
    assert tony_page.acceptNavigationRequest(QUrl(url), kind, True) is False
    assert opened == []


class FakePermission:
    def __init__(self, kind):
        self.kind = kind
        self.denied = 0
        self.granted = 0

    def permissionType(self):
        return self.kind

    def deny(self):
        self.denied += 1

    def grant(self):
        self.granted += 1


@pytest.mark.parametrize(
    "kind",
    [
        Permission.MediaAudioCapture,
        Permission.MediaVideoCapture,
        Permission.Geolocation,
        Permission.Notifications,
        Permission.ClipboardReadWrite,
    ],
)
def test_every_permission_request_is_denied(page, kind):
    tony_page, _ = page
    permission = FakePermission(kind)
    tony_page.deny_permission(permission)
    assert (permission.denied, permission.granted) == (1, 0)


def test_permission_requests_go_to_the_deny_handler(page):
    tony_page, _ = page
    assert tony_page.receivers("2permissionRequested(QWebEnginePermission)") == 1


def test_popups_are_refused(page):
    tony_page, _ = page
    assert tony_page.createWindow(QWebEnginePage.WebWindowType.WebBrowserTab) is None


def test_page_uses_the_off_the_record_profile(page):
    tony_page, _ = page
    assert tony_page.profile() is QWebEngineProfile.defaultProfile()
    assert tony_page.profile().isOffTheRecord()


def test_local_content_can_load_files_but_not_remote_urls(page):
    tony_page, _ = page
    settings = tony_page.settings()
    Attribute = QWebEngineSettings.WebAttribute
    assert settings.testAttribute(Attribute.LocalContentCanAccessFileUrls) is True
    assert settings.testAttribute(Attribute.LocalContentCanAccessRemoteUrls) is False


def test_qwebchannel_script_is_injected_at_document_creation(page):
    tony_page, _ = page
    [script] = tony_page.scripts().find(CHANNEL_SCRIPT)
    assert script.injectionPoint() == QWebEngineScript.InjectionPoint.DocumentCreation
    assert script.worldId() == QWebEngineScript.ScriptWorldId.MainWorld
    assert "QWebChannel" in script.sourceCode()


def test_web_view_registers_the_bridge_and_disables_the_context_menu(qapp, tmp_path):
    bridge = PageBridge(lambda command: None, lambda event: None, tmp_path, now=lambda: None)
    view = create_web_view(HOME, bridge)
    try:
        assert view.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu
        assert isinstance(view.page(), TonyPage)
        assert view.page().webChannel().registeredObjects() == {"tony": bridge}
        assert view.url().isEmpty()
    finally:
        shiboken6.delete(view)
