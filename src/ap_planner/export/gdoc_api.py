"""Rewrite an EXISTING Google Doc in place (same id, same link) via ``documents.batchUpdate``.

The Drive connector cannot replace a file's content, but the Docs connector (``update_doc``)
can run batchUpdate requests. This module turns the doc blocks of ``gdoc.operation_blocks``
into such requests: delete the old body, then append paragraph by paragraph and table by table
while tracking the document index (UTF-16 code units), with the same look as the HTML version.

Docs index rules used here:
- the body starts at index 1; the last paragraph's newline can never be deleted
- ``insertTable`` at index i first inserts a newline, so the table starts at i + 1
- a table of R rows x C cols: table start (1) + per row: row start (1) + per cell: cell
  start (1) + its empty paragraph (1). Cell (r, c) text goes to
  ``start + 3 + r * (2C + 1) + 2c``. Cells are filled from the last to the first, so the
  indices of the cells not yet filled never move. After the last row the table takes one more
  index, then the next paragraph starts (verified against the live API).
"""

import re
from html import unescape
from typing import Any

from ap_planner.export import gdoc
from ap_planner.export.gdoc import Block, Bullets, Para, Table

Request = dict[str, Any]

_TAG = re.compile(r'<b>|</b>|<a href="([^"]*)">|</a>')


def _len16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _rgb(hex_color: str) -> dict[str, Any]:
    h = hex_color.lstrip("#")
    r, g, b = (round(int(h[i : i + 2], 16) / 255, 3) for i in (0, 2, 4))
    return {"color": {"rgbColor": {"red": r, "green": g, "blue": b}}}


def _runs(markup: str) -> list[tuple[str, bool, str | None]]:
    """Mini-HTML -> [(text, bold, link)]."""
    out: list[tuple[str, bool, str | None]] = []
    bold, link, pos = False, None, 0
    for m in _TAG.finditer(markup):
        if m.start() > pos:
            out.append((unescape(markup[pos : m.start()]), bold, link))
        tag = m.group(0)
        if tag == "<b>":
            bold = True
        elif tag == "</b>":
            bold = False
        elif tag == "</a>":
            link = None
        else:
            link = unescape(m.group(1))
        pos = m.end()
    if pos < len(markup):
        out.append((unescape(markup[pos:]), bold, link))
    return out


# kind -> (font size pt, bold, italic, color, space above, space below, named style)
_PARA_LOOK: dict[str, tuple[float, bool, bool, str, float, float, str]] = {
    "title": (22, True, False, gdoc.DARK_RED, 0, 6, "TITLE"),
    "subtitle": (10.5, False, True, gdoc.GREY_TEXT, 0, 0, "NORMAL_TEXT"),
    "h1": (15, True, False, gdoc.DARK_RED, 16, 6, "HEADING_1"),
    "p": (10.5, False, False, "#000000", 0, 0, "NORMAL_TEXT"),
    "note": (10.5, False, True, gdoc.GREY_TEXT, 0, 0, "NORMAL_TEXT"),
    "bullet": (10.5, False, False, "#000000", 0, 0, "NORMAL_TEXT"),
}
_CELL_PT = 9.5


def _rng(start: int, end: int) -> dict[str, int]:
    return {"startIndex": start, "endIndex": end}


class _Writer:
    def __init__(self) -> None:
        self.idx = 1  # start of the (empty) last paragraph = where the next block goes
        self.reqs: list[Request] = []

    def text_style(self, start: int, end: int, style: dict[str, Any], fields: str) -> None:
        if end > start:
            self.reqs.append(
                {
                    "updateTextStyle": {
                        "range": _rng(start, end),
                        "textStyle": style,
                        "fields": fields,
                    }
                }
            )

    def paragraph(self, kind: str, markup: str) -> tuple[int, int]:
        runs = _runs(markup) or [("", False, None)]
        text = "".join(r[0] for r in runs) + "\n"
        start = self.idx
        end = start + _len16(text)
        size, bold, italic, color, above, below, named = _PARA_LOOK[kind]
        self.reqs.append({"insertText": {"location": {"index": start}, "text": text}})
        self.reqs.append(
            {
                "updateParagraphStyle": {
                    "range": _rng(start, end),
                    "paragraphStyle": {
                        "namedStyleType": named,
                        "spaceAbove": {"magnitude": above, "unit": "PT"},
                        "spaceBelow": {"magnitude": below, "unit": "PT"},
                    },
                    "fields": "namedStyleType,spaceAbove,spaceBelow",
                }
            }
        )
        base = {
            "fontSize": {"magnitude": size, "unit": "PT"},
            "bold": bold,
            "italic": italic,
            "foregroundColor": _rgb(color),
        }
        self.text_style(start, end, base, "fontSize,bold,italic,foregroundColor")
        pos = start
        for run_text, run_bold, link in runs:
            n = _len16(run_text)
            if run_bold and not bold:
                self.text_style(pos, pos + n, {"bold": True}, "bold")
            if link:
                self.text_style(pos, pos + n, {"link": {"url": link}}, "link")
            pos += n
        self.idx = end
        return start, end

    def bullets(self, items: list[str]) -> None:
        if not items:
            return
        start = self.idx
        for item in items:
            self.paragraph("bullet", item)
        self.reqs.append(
            {
                "createParagraphBullets": {
                    "range": _rng(start, self.idx - 1),
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            }
        )

    def table(self, rows: list[tuple[str, ...]]) -> None:
        all_rows = [gdoc.HEADER, *rows]
        n_rows, n_cols = len(all_rows), len(gdoc.HEADER)
        at = self.idx
        self.reqs.append(
            {"insertTable": {"rows": n_rows, "columns": n_cols, "location": {"index": at}}}
        )
        tstart = at + 1
        loc = {"index": tstart}
        for i, width in enumerate(gdoc.COL_WIDTH_PT):
            self.reqs.append(
                {
                    "updateTableColumnProperties": {
                        "tableStartLocation": loc,
                        "columnIndices": [i],
                        "tableColumnProperties": {
                            "widthType": "FIXED_WIDTH",
                            "width": {"magnitude": width, "unit": "PT"},
                        },
                        "fields": "widthType,width",
                    }
                }
            )
        self.reqs.append(
            {
                "updateTableCellStyle": {
                    "tableRange": {
                        "tableCellLocation": {
                            "tableStartLocation": loc,
                            "rowIndex": 0,
                            "columnIndex": 0,
                        },
                        "rowSpan": 1,
                        "columnSpan": n_cols,
                    },
                    "tableCellStyle": {"backgroundColor": _rgb(gdoc.HEADER_BG)},
                    "fields": "backgroundColor",
                }
            }
        )
        filled = 0
        for r in range(n_rows - 1, -1, -1):
            for c in range(n_cols - 1, -1, -1):
                text = all_rows[r][c]
                if c == 4 and r > 0:  # "Was": coloured by kind
                    bg = gdoc.KIND_BG.get(text.split(" →", maxsplit=1)[0])
                    if bg:
                        self.reqs.append(
                            {
                                "updateTableCellStyle": {
                                    "tableRange": {
                                        "tableCellLocation": {
                                            "tableStartLocation": loc,
                                            "rowIndex": r,
                                            "columnIndex": c,
                                        },
                                        "rowSpan": 1,
                                        "columnSpan": 1,
                                    },
                                    "tableCellStyle": {"backgroundColor": _rgb(bg)},
                                    "fields": "backgroundColor",
                                }
                            }
                        )
                if not text:
                    continue
                pos = tstart + 3 + r * (2 * n_cols + 1) + 2 * c
                self.reqs.append({"insertText": {"location": {"index": pos}, "text": text}})
                filled += _len16(text)
        end = tstart + 1 + n_rows * (2 * n_cols + 1) + filled
        # one base style for the whole table, then bold header + first two columns
        self.text_style(
            tstart,
            end,
            {
                "fontSize": {"magnitude": _CELL_PT, "unit": "PT"},
                "bold": False,
                "italic": False,
                "foregroundColor": _rgb("#000000"),
            },
            "fontSize,bold,italic,foregroundColor",
        )
        before = 0  # text of all earlier cells (document order) shifts a cell's position
        for r in range(n_rows):
            for c in range(n_cols):
                n = _len16(all_rows[r][c])
                pos = tstart + 3 + r * (2 * n_cols + 1) + 2 * c + before
                if n and (r == 0 or c < 2):
                    self.text_style(pos, pos + n, {"bold": True}, "bold")
                before += n
        # the table ends with one more index after its last row; the next paragraph follows
        self.idx = end + 1


def rewrite_requests(blocks: list[Block], end_index: int) -> list[Request]:
    """batchUpdate requests that replace the whole body of a doc whose body ends at
    ``end_index`` (``body.content[-1].endIndex`` from ``read_doc``)."""
    w = _Writer()
    if end_index - 1 > 1:
        w.reqs.append({"deleteContentRange": {"range": _rng(1, end_index - 1)}})
    w.reqs.append(
        {
            "updateDocumentStyle": {
                "documentStyle": {
                    "pageSize": {
                        "width": {"magnitude": 842, "unit": "PT"},
                        "height": {"magnitude": 595, "unit": "PT"},
                    },
                    "marginTop": {"magnitude": 50, "unit": "PT"},
                    "marginBottom": {"magnitude": 50, "unit": "PT"},
                    "marginLeft": {"magnitude": 50, "unit": "PT"},
                    "marginRight": {"magnitude": 50, "unit": "PT"},
                },
                "fields": "pageSize,marginTop,marginBottom,marginLeft,marginRight",
            }
        }
    )
    for b in blocks:
        if isinstance(b, Table):
            w.table(b.rows)
        elif isinstance(b, Bullets):
            w.bullets(b.items)
        elif isinstance(b, Para):
            w.paragraph(b.kind, b.html)
    w.text_style(1, w.idx, {"weightedFontFamily": {"fontFamily": "Arial"}}, "weightedFontFamily")
    return w.reqs
