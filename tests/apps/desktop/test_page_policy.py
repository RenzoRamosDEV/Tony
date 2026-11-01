from pathlib import Path

import pytest

import tony.apps.desktop
from tony.apps.desktop.page_policy import (
    BUILD_COMMAND,
    missing_build_message,
    navigation_decision,
    web_dist,
)

HOME = "file:///x/dist/index.html"


@pytest.mark.parametrize("url", [HOME, HOME + "#frag", HOME + "#"])
@pytest.mark.parametrize("link_click", [True, False])
def test_home_is_allowed_ignoring_the_fragment(url, link_click):
    assert navigation_decision(url, HOME, link_click=link_click) == "allow"


@pytest.mark.parametrize("url", ["https://example.org/", "http://a.test", "HTTPS://Example.org/x"])
def test_http_link_clicks_open_externally(url):
    assert navigation_decision(url, HOME, link_click=True) == "external"


@pytest.mark.parametrize("url", ["https://example.org/", "http://a.test"])
def test_http_navigation_that_is_not_a_link_click_is_blocked(url):
    assert navigation_decision(url, HOME, link_click=False) == "block"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file:///x/dist/other.html",
        "file:///x/dist/index.html?q=1",
        "file:///x/dist/index.htm",
        "javascript:alert(1)",
        "data:text/html,x",
        "mailto:a@b.c",
        "tony://x",
        "https:",
        "",
    ],
)
@pytest.mark.parametrize("link_click", [True, False])
def test_everything_else_is_blocked(url, link_click):
    assert navigation_decision(url, HOME, link_click=link_click) == "block"


def test_web_dist_is_the_build_output_next_to_the_package():
    expected = Path(tony.apps.desktop.__file__).parent / "web" / "dist"
    assert web_dist() == expected
    assert web_dist().parts[-5:] == ("tony", "apps", "desktop", "web", "dist")


def test_missing_build_message_contains_the_exact_build_command():
    assert BUILD_COMMAND == (
        "npm --prefix tony/apps/desktop/web ci && npm --prefix tony/apps/desktop/web run build"
    )
    assert BUILD_COMMAND in missing_build_message(Path("/x/dist"))
    assert "/x/dist/index.html" in missing_build_message(Path("/x/dist"))
