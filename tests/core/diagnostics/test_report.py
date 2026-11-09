from tony.core.diagnostics.checks import Check
from tony.core.diagnostics.report import exit_code, format_report


def test_report_is_a_table_with_header_and_one_row_per_check():
    report = format_report([Check("a", "ok", "fine"), Check("longer-name", "warn", "do x")])

    assert report.splitlines() == [
        "check        status  hint",
        "a            ok      fine",
        "longer-name  warn    do x",
    ]


def test_empty_report_has_only_the_header():
    assert format_report([]).split() == ["check", "status", "hint"]


def test_exit_code_is_1_when_any_check_fails():
    assert exit_code([Check("a", "ok", ""), Check("b", "fail", "x"), Check("c", "warn", "")]) == 1


def test_warnings_alone_exit_0():
    assert exit_code([Check("a", "warn", "x"), Check("b", "ok", "")]) == 0


def test_no_checks_exit_0():
    assert exit_code([]) == 0
