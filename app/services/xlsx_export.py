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
TEXT, INT, NUMBER, MONEY, PERCENT, MIXED, DATETIME, DATE = "text", "int", "number", "money", "percent", "mixed", "datetime", "date"
FORMATS = {INT: "#,##0", NUMBER: "#,##0.00", MONEY: '"₹"#,##0.00', PERCENT: '0.0"%"'}   # "₹" is quoted so Excel always reads it as a literal
DATE_FORMATS = {DATETIME: "dd mmm yyyy, hh:mm", DATE: "dd mmm yyyy"}                    # real Excel dates (they sort and filter as dates)

HEADER_FILL = PatternFill("solid", start_color="183D2B")      # the panel's dark green
ZEBRA_FILL = PatternFill("solid", start_color="EEF6F0")
HEADER_FONT = Font(bold=True, color="FFFFFF")
_SIDE = Side(style="thin", color="B7C4BB")
BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)
MIN_WIDTH, MAX_WIDTH, MAX_TEXT = 8, 60, 32000     # Excel allows 32,767 characters in a cell

# A value that carries its own kind (used on the Summary sheet, where each row is a different kind of number).
Typed = namedtuple("Typed", "value kind")


TITLE_FONT = Font(bold=True, size=14, color="183D2B")
LABEL_FONT = Font(bold=True, color="243C2C")
NOTE_FONT = Font(italic=True, color="5B6B60")
TOTAL_FILL = PatternFill("solid", start_color="DCEBDF")
TOTAL_FONT = Font(bold=True, color="183D2B")


@dataclass
class Sheet:
    """One worksheet. `report_title`, `notes` and `summary` (a list of (label, value, kind)) sit above the table, and `totals`
    (one cell per column, None for blank) is a bold row under it. All four are optional, so a plain table is just headers + rows."""
    title: str
    headers: list[str]
    kinds: list[str]
    rows: list[list]
    report_title: str | None = None
    notes: list[str] | None = None
    summary: list[tuple] | None = None
    totals: list | None = None


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


def _text(value, clean) -> str:
    text = "" if value is None else ILLEGAL_CHARACTERS_RE.sub("", str(value))[:MAX_TEXT]
    return clean(text) if clean is not None else text


def _write_preamble(ws, sheet: Sheet, clean, widths) -> int:
    """Title, notes and the summary block above the table. Returns the row number of the table header."""
    row = 1
    if sheet.report_title:
        c = ws.cell(row=row, column=1, value=_text(sheet.report_title, clean))
        c.data_type, c.font = "s", TITLE_FONT
        ws.row_dimensions[row].height = 24
        row += 1
    for note in sheet.notes or []:
        c = ws.cell(row=row, column=1, value=_text(note, clean))
        c.data_type, c.font = "s", NOTE_FONT
        row += 1
    if sheet.summary:
        if row > 1:
            row += 1                                          # a blank line before the summary
        for label, value, kind in sheet.summary:
            a = ws.cell(row=row, column=1, value=_text(label, clean))
            a.data_type, a.font, a.alignment = "s", LABEL_FONT, Alignment(horizontal="left", vertical="center")
            widths[0] = max(widths[0], len(str(label)) + 2)
            b = ws.cell(row=row, column=2)
            number = _number(value, kind) if kind in FORMATS else None
            if number is not None:
                b.value, b.number_format = number, FORMATS[kind]
                b.alignment = Alignment(horizontal="right", vertical="center")
            elif kind in DATE_FORMATS and value is not None:
                b.value, b.number_format = value, DATE_FORMATS[kind]
                b.alignment = Alignment(horizontal="right", vertical="center")
            else:
                text = _text(value, clean) or "-"
                b.value, b.data_type = text, "s"
                b.alignment = Alignment(horizontal="left", vertical="center")
            b.font = Font(bold=True)
            row += 1
    if row > 1:
        row += 1                                              # a blank line before the table
    return row


def _write_sheet(ws, sheet: Sheet, clean) -> None:
    widths = [len(h) + 4 for h in sheet.headers]             # + room for the filter arrow
    head_row = _write_preamble(ws, sheet, clean, widths)
    for col, (head, kind) in enumerate(zip(sheet.headers, sheet.kinds), start=1):
        cell = ws.cell(row=head_row, column=col, value=head)
        cell.data_type = "s"
        cell.font, cell.fill, cell.border = HEADER_FONT, HEADER_FILL, BORDER
        cell.alignment = Alignment(horizontal="right" if (kind in FORMATS) else "left", vertical="center", wrap_text=True)
    ws.row_dimensions[head_row].height = 22

    for r, row in enumerate(sheet.rows, start=head_row + 1):
        zebra = r % 2 == 1                                   # every second data row
        for col, raw in enumerate(row, start=1):
            value, kind = (raw.value, raw.kind) if isinstance(raw, Typed) else (raw, sheet.kinds[col - 1])
            cell = ws.cell(row=r, column=col)
            number = _number(value, kind) if kind in FORMATS else None
            if kind in DATE_FORMATS and value is not None and hasattr(value, "year"):
                cell.value, cell.number_format = value, DATE_FORMATS[kind]
                shown, align_kind = "00 Mon 0000, 00:00" if kind == DATETIME else "00 Mon 0000", TEXT
            elif number is not None:
                cell.value = number
                cell.number_format = FORMATS[kind]
                shown, align_kind = _display(number, kind), kind
            else:
                text = _text(value, clean)
                if text:
                    cell.value = text
                    cell.data_type = "s"                     # never a formula, whatever the text starts with
                shown, align_kind = text.split("\n", 1)[0], TEXT
            cell.alignment = _align(align_kind)
            cell.border = BORDER
            if zebra:
                cell.fill = ZEBRA_FILL
            widths[col - 1] = max(widths[col - 1], len(shown) + 2)

    last_data = head_row + len(sheet.rows)
    if sheet.totals:
        tr = last_data + 1
        for col, raw in enumerate(sheet.totals, start=1):
            kind = sheet.kinds[col - 1]
            cell = ws.cell(row=tr, column=col)
            number = _number(raw, kind) if kind in FORMATS else None
            if number is not None:
                cell.value, cell.number_format = number, FORMATS[kind]
                shown, align_kind = _display(number, kind), kind
            elif raw not in (None, ""):
                cell.value, cell.data_type = _text(raw, clean), "s"
                shown, align_kind = str(raw), TEXT
            else:
                shown, align_kind = "", TEXT
            cell.font, cell.fill, cell.border = TOTAL_FONT, TOTAL_FILL, BORDER
            cell.alignment = _align(align_kind)
            widths[col - 1] = max(widths[col - 1], len(shown) + 2)

    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = max(MIN_WIDTH, min(MAX_WIDTH, width))
    ws.freeze_panes = f"A{head_row + 1}"
    ws.auto_filter.ref = f"A{head_row}:{get_column_letter(len(sheet.headers))}{max(head_row, last_data)}"
    ws.print_title_rows = f"{head_row}:{head_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
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
