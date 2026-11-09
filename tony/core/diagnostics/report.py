from collections.abc import Sequence

from tony.core.diagnostics.checks import Check

COLUMNS = ("check", "status", "hint")


def format_report(checks: Sequence[Check]) -> str:
    rows = [COLUMNS, *((check.name, check.status, check.hint) for check in checks)]
    widths = [max(len(row[index]) for row in rows) for index in range(len(COLUMNS))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def exit_code(checks: Sequence[Check]) -> int:
    return 1 if any(check.status == "fail" for check in checks) else 0
