"""Styled Excel (.xlsx) exports, built with openpyxl.

One look for every export: dark green header with bold white text, frozen header row, auto-filter, columns sized to their
content, text on the left and numbers on the right, ₹ money format, thin borders and zebra rows.

The builder never writes a formula: every text cell is forced to a string, and callers can pass `clean` (the CSV code passes
`safe_cell`) so a value starting with = + - @ is neutralised exactly as it is in the CSV export.
"""
from __future__ import annotations

import io
from collections import namedtuple
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# column kinds
TEXT, INT, NUMBER, MONEY, PERCENT, MIXED = "text", "int", "number", "money", "percent", "mixed"
FORMATS = {INT: "#,##0", NUMBER: "#,##0.00", MONEY: '"₹"#,##0.00', PERCENT: '0.0"%"'}   # "₹" is quoted so Excel always reads it as a literal

HEADER_FILL = PatternFill("solid", start_color="183D2B")      # the panel's dark green
ZEBRA_FILL = PatternFill("solid", start_color="EEF6F0")
HEADER_FONT = Font(bold=True, color="FFFFFF")
_SIDE = Side(style="thin", color="B7C4BB")
BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)
MIN_WIDTH, MAX_WIDTH, MAX_TEXT = 8, 60, 32000     # Excel allows 32,767 characters in a cell

# A value that carries its own kind (used on the Summary sheet, where each row is a different kind of number).
Typed = namedtuple("Typed", "value kind")


@dataclass
class Sheet:
    title: str
    headers: list[str]
    kinds: list[str]
    rows: list[list]


def _number(value, kind):
    """The value as a number, or None if it is not one (then it is written as text)."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not num.is_finite():
        return None
    return int(num) if kind == INT else float(num)


def _display(value, kind) -> str:
    """What the cell will look like on screen; used to size the column."""
    if kind == MONEY:
        return f"₹{value:,.2f}"
    if kind == NUMBER:
        return f"{value:,.2f}"
    if kind == INT:
        return f"{value:,}"
    if kind == PERCENT:
        return f"{value:.1f}%"
    return str(value)


def _align(kind) -> Alignment:
    right = kind in FORMATS
    return Alignment(horizontal="right" if right else "left", vertical="center")


def _write_sheet(ws, sheet: Sheet, clean) -> None:
    widths = [len(h) + 4 for h in sheet.headers]             # + room for the filter arrow
    for col, (head, kind) in enumerate(zip(sheet.headers, sheet.kinds), start=1):
        cell = ws.cell(row=1, column=col, value=head)
        cell.data_type = "s"
        cell.font, cell.fill, cell.border = HEADER_FONT, HEADER_FILL, BORDER
        cell.alignment = _align(kind)
    ws.row_dimensions[1].height = 22

    for r, row in enumerate(sheet.rows, start=2):
        zebra = r % 2 == 1                                   # every second data row
        for col, raw in enumerate(row, start=1):
            value, kind = (raw.value, raw.kind) if isinstance(raw, Typed) else (raw, sheet.kinds[col - 1])
            cell = ws.cell(row=r, column=col)
            number = _number(value, kind) if kind in FORMATS else None
            if number is not None:
                cell.value = number
                cell.number_format = FORMATS[kind]
                shown, align_kind = _display(number, kind), kind
            else:
                text = "" if value is None else ILLEGAL_CHARACTERS_RE.sub("", str(value))[:MAX_TEXT]
                if clean is not None:
                    text = clean(text)
                if text:
                    cell.value = text
                    cell.data_type = "s"                     # never a formula, whatever the text starts with
                shown, align_kind = text.split("\n", 1)[0], TEXT
            cell.alignment = _align(align_kind)
            cell.border = BORDER
            if zebra:
                cell.fill = ZEBRA_FILL
            widths[col - 1] = max(widths[col - 1], len(shown) + 2)

    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = max(MIN_WIDTH, min(MAX_WIDTH, width))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(sheet.headers))}{max(1, len(sheet.rows) + 1)}"
    ws.print_title_rows = "1:1"
    ws.sheet_view.zoomScale = 100


def build_workbook(sheets: list[Sheet], *, clean=None) -> bytes:
    """Returns the finished .xlsx file as bytes."""
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.creator = "RR FOODS"
    for sheet in sheets:
        _write_sheet(wb.create_sheet(sheet.title[:31]), sheet, clean)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
