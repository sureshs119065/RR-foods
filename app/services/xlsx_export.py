"""Styled Excel (.xlsx) exports, built with openpyxl.

One look for every export: dark green header with bold white text, frozen header row, auto-filter, columns sized to their
content, text on the left and numbers on the right, ₹ money format, thin borders and zebra rows.

The builder never writes a formula: every text cell is forced to a string, and callers can pass `clean` (the exports pass
`safe_cell`) so a value starting with = + - @ is neutralised.
"""
from __future__ import annotations

import io
import math
from collections import namedtuple
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.chart import BarChart, DoughnutChart, Reference
from openpyxl.chart.data_source import NumFmt
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties, RichTextProperties
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


# ------------------------------------------------------------------ Insights sheet: native charts + suggestion boxes
# Brand colours for every chart: the panel's dark green first, then lighter greens and one warm accent.
CHART_COLORS = ["183D2B", "47764F", "78A982", "C9A227", "B7C4BB", "8C5E2A"]
SUGGESTION_FILL = PatternFill("solid", start_color="FFF8CC")             # light yellow
SUGGESTION_FONT = Font(size=10, color="3A3A1E")
BLOCK_FONT = Font(bold=True, size=11, color="183D2B")
MONEY_LABEL = '"₹"#,##0'                                                  # chart axes and data labels (whole rupees keep them readable)

BOX_COLS = 8            # the chart and the suggestion boxes span columns A:H
BOX_CHARS = 100         # roughly how many characters of 10 pt text fit on one line of A:H
CHART_ROWS = 16         # rows reserved for a chart (8 cm is about 15 default rows)
TABLE_COL = 10          # the chart's data table sits beside it, in J:L


@dataclass
class ChartBlock:
    """One block of the Insights sheet: a heading, a data table, a native chart that reads that table, and suggestion boxes.
    kind is "bar" (columns), "hbar" (horizontal bars), "doughnut", or "text" (suggestion boxes only, no chart)."""
    title: str
    kind: str = "bar"
    headers: list[str] = field(default_factory=list)          # table headers; the first column holds the category labels
    kinds: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    plot: list[int] = field(default_factory=lambda: [1])      # indexes of the columns that are drawn (0 is the category column)
    x_title: str = ""
    y_title: str = ""
    colors: list[str] | None = None                            # one colour per slice (doughnut)
    empty_note: str = "No data for this period yet, so there is no chart."
    suggestions: list[tuple[str, str]] = field(default_factory=list)   # (title, text)


@dataclass
class InsightsSheet:
    """The "Insights" worksheet. `chips` are coloured count tiles: (label, count, fill hex, font hex)."""
    title: str = "Insights"
    report_title: str = "RR FOODS — Insights"
    notes: list[str] = field(default_factory=list)
    chips: list[tuple] = field(default_factory=list)
    blocks: list[ChartBlock] = field(default_factory=list)


def _labels(*, percent=False, fmt=None, rotate=False) -> DataLabelList:
    dl = DataLabelList()
    if percent:
        dl.spPr = GraphicalProperties(solidFill="FFFFFF")
    dl.showVal, dl.showPercent = (not percent), percent
    dl.showSerName = dl.showCatName = dl.showLegendKey = dl.showLeaderLines = False      # said out loud: Excel and LibreOffice default differently
    if fmt:
        dl.numFmt = fmt
    if not percent:
        dl.position = "outEnd"
    size = 800 if rotate else 900
    props = RichTextProperties(rot=-5400000, vert="horz") if rotate else RichTextProperties()
    dl.txPr = RichText(bodyPr=props, p=[Paragraph(pPr=ParagraphProperties(defRPr=CharacterProperties(sz=size)), endParaRPr=CharacterProperties())])
    return dl


def _title(chart_or_axis, text: str) -> None:
    chart_or_axis.title = text
    chart_or_axis.title.overlay = False


def _make_chart(ws, block: ChartBlock, top: int, last: int):
    """A native chart whose series point at the block's table on this sheet (header row `top`, data rows top+1 .. last)."""
    cats = Reference(ws, min_col=TABLE_COL, min_row=top + 1, max_row=last)
    money = any(block.kinds[i] == MONEY for i in block.plot)
    fmt = MONEY_LABEL if money else "#,##0"
    if block.kind == "doughnut":
        chart = DoughnutChart()
        chart.holeSize = 55
        chart.add_data(Reference(ws, min_col=TABLE_COL + block.plot[0], min_row=top, max_row=last), titles_from_data=True)
        chart.set_categories(cats)
        for i in range(last - top):
            point = DataPoint(idx=i)
            point.graphicalProperties.solidFill = (block.colors or CHART_COLORS)[i % len(block.colors or CHART_COLORS)]
            chart.series[0].dPt.append(point)
        chart.dataLabels = _labels(percent=True, fmt="0%")
        chart.legend.position = "r"
    else:
        chart = BarChart()
        chart.type = "bar" if block.kind == "hbar" else "col"
        chart.grouping = "clustered"
        chart.gapWidth = 60
        for n, idx in enumerate(block.plot):
            chart.add_data(Reference(ws, min_col=TABLE_COL + idx, min_row=top, max_row=last), titles_from_data=True)
            series = chart.series[n]
            color = CHART_COLORS[n % len(CHART_COLORS)]
            series.graphicalProperties.solidFill = color
            series.graphicalProperties.line.solidFill = color
            series.invertIfNegative = False
        chart.set_categories(cats)
        chart.dataLabels = _labels(fmt=fmt, rotate=(block.kind == "bar" and last - top > 14))
        _title(chart.x_axis, block.x_title)
        _title(chart.y_axis, block.y_title)
        chart.x_axis.delete = chart.y_axis.delete = False
        chart.y_axis.numFmt = NumFmt(formatCode=fmt, sourceLinked=False)
        chart.y_axis.scaling.min = 0
        if block.kind == "hbar":
            chart.x_axis.scaling.orientation = "maxMin"          # first row at the top ...
            chart.y_axis.crosses = "max"                         # ... with the value axis still along the bottom
        if len(block.plot) > 1:
            chart.legend.position = "b"
        else:
            chart.legend = None
    if chart.legend is not None:
        chart.legend.overlay = False
    _title(chart, block.title)
    chart.roundedCorners = False
    chart.width, chart.height = 19.5, 8.0
    return chart


def _write_table(ws, top: int, block: ChartBlock, clean) -> int:
    """The block's data table in J:L (dark green header, thin borders, zebra rows). Returns the last row used."""
    for i, (head, kind) in enumerate(zip(block.headers, block.kinds)):
        cell = ws.cell(row=top, column=TABLE_COL + i, value=head)
        cell.data_type = "s"
        cell.font, cell.fill, cell.border = HEADER_FONT, HEADER_FILL, BORDER
        cell.alignment = Alignment(horizontal="right" if kind in FORMATS else "left", vertical="center")      # one line: a taller row would push the charts below it out of place in some viewers
    for r, row in enumerate(block.rows, start=top + 1):
        for i, (raw, kind) in enumerate(zip(row, block.kinds)):
            cell = ws.cell(row=r, column=TABLE_COL + i)
            number = _number(raw, kind) if kind in FORMATS else None
            if number is not None:
                cell.value, cell.number_format = number, FORMATS[kind]
                cell.alignment = _align(kind)
            else:
                text = _text(raw, clean)
                if text:
                    cell.value, cell.data_type = text, "s"
                cell.alignment = _align(TEXT)
            cell.border = BORDER
            if r % 2 == 1:
                cell.fill = ZEBRA_FILL
    return top + len(block.rows)


def _suggestion_box(ws, row: int, title: str, text: str, clean) -> int:
    """A light-yellow box of merged, wrapped cells across A:H. Returns the next free row."""
    body = f"Suggestion — {title}\n{text}" if title else f"Suggestion\n{text}"
    height = max(2, sum(max(1, math.ceil(len(part) / BOX_CHARS)) for part in body.split("\n")))
    end = row + height - 1
    for r in range(row, end + 1):
        for c in range(1, BOX_COLS + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill, cell.border = SUGGESTION_FILL, BORDER
    anchor = ws.cell(row=row, column=1)
    anchor.value, anchor.data_type = _text(body, clean), "s"
    anchor.font, anchor.alignment = SUGGESTION_FONT, Alignment(wrap_text=True, vertical="top", horizontal="left")
    ws.merge_cells(start_row=row, start_column=1, end_row=end, end_column=BOX_COLS)
    return end + 1


ROW_HEIGHT = 15                                  # every row on the Insights sheet gets an explicit height (below), so no viewer auto-sizes a row
TALL_ROWS = {"title": 22, "heading": 18, "chip_number": 24}        # and moves the charts, which are positioned by row, out of line


def _write_insights(ws, sheet: InsightsSheet, clean) -> None:
    heights: dict[int, int] = {}
    row = 1
    heights[row] = TALL_ROWS["title"]
    c = ws.cell(row=row, column=1, value=_text(sheet.report_title, clean))
    c.data_type, c.font = "s", TITLE_FONT
    row += 1
    for note in sheet.notes:
        c = ws.cell(row=row, column=1, value=_text(note, clean))
        c.data_type, c.font = "s", NOTE_FONT
        row += 1
    row += 1
    if sheet.chips:                                                  # coloured count tiles: label above, number below
        for i, (label, count, fill, color) in enumerate(sheet.chips):
            col = 1 + 2 * i
            for r in (row, row + 1):
                for cc in (col, col + 1):
                    ws.cell(row=r, column=cc).fill = PatternFill("solid", start_color=fill)
                    ws.cell(row=r, column=cc).border = BORDER
            a = ws.cell(row=row, column=col, value=_text(label, clean))
            a.data_type, a.font, a.alignment = "s", Font(bold=True, size=10, color=color), Alignment(horizontal="center", vertical="center")
            b = ws.cell(row=row + 1, column=col, value=int(count))
            b.number_format, b.font, b.alignment = FORMATS[INT], Font(bold=True, size=14, color=color), Alignment(horizontal="center", vertical="center")
            ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 1)
            ws.merge_cells(start_row=row + 1, start_column=col, end_row=row + 1, end_column=col + 1)
        heights[row + 1] = TALL_ROWS["chip_number"]
        row += 3

    for block in sheet.blocks:
        head = ws.cell(row=row, column=1, value=_text(block.title, clean))
        head.data_type, head.font = "s", BLOCK_FONT
        for col in range(1, TABLE_COL + 3):
            ws.cell(row=row, column=col).fill = TOTAL_FILL
        heights[row] = TALL_ROWS["heading"]
        top, table_end = row + 1, row + 1
        if block.kind == "text":
            box_row = top
        else:
            n = len(block.rows)
            has_chart = n > 0 and any(_number(r[i], block.kinds[i]) not in (None, 0) for r in block.rows for i in block.plot)
            if has_chart:
                table_end = _write_table(ws, top, block, clean)
                ws.add_chart(_make_chart(ws, block, top, table_end), f"A{top}")
                box_row = top + CHART_ROWS
            else:                                                    # nothing to draw: say so, and still leave a valid sheet
                note = ws.cell(row=top, column=1, value=_text(block.empty_note, clean))
                note.data_type, note.font = "s", NOTE_FONT
                box_row = top + 2
        end = box_row
        for title, text in block.suggestions:
            end = _suggestion_box(ws, end, title, text, clean)
        row = max(end, table_end + 1) + 1

    for r in range(1, row + 1):
        ws.row_dimensions[r].height = heights.get(r, ROW_HEIGHT)
    for col in range(1, BOX_COLS + 1):
        ws.column_dimensions[get_column_letter(col)].width = 13
    ws.column_dimensions[get_column_letter(TABLE_COL - 1)].width = 3
    ws.column_dimensions[get_column_letter(TABLE_COL)].width = 30
    for col in (TABLE_COL + 1, TABLE_COL + 2):
        ws.column_dimensions[get_column_letter(col)].width = 22
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def build_workbook(sheets: list, *, clean=None) -> bytes:
    """Returns the finished .xlsx file as bytes. Each item is a `Sheet` (a table) or an `InsightsSheet` (native charts + suggestions)."""
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.creator = "RR FOODS"
    for sheet in sheets:
        ws = wb.create_sheet(sheet.title[:31])
        (_write_insights if isinstance(sheet, InsightsSheet) else _write_sheet)(ws, sheet, clean)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
