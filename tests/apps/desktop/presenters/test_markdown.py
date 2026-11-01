from tony.apps.desktop.presenters.markdown import MarkdownRenderer

render = MarkdownRenderer().render


def test_bold():
    assert render("Buenas **tardes**") == "<p>Buenas <strong>tardes</strong></p>\n"


def test_fenced_code():
    assert "<pre><code" in render("```python\nprint(1)\n```")


def test_pipe_table():
    html = render("| a | b |\n|---|---|\n| 1 | 2 |")

    assert "<table>" in html and "<td>1</td>" in html


def test_raw_html_is_escaped():
    html = render("<script>alert(1)</script>")

    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_empty_text():
    assert render("") == ""
