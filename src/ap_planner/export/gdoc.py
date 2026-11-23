"""Operation document for the players (HTML that Google Docs converts into a normal Doc).

Layout follows the tribe's hand-made doc: title, subtitle, "Worum geht es?", "Wichtig beim
Abschicken", one section per target (setup sentence + table in landing order) and at the end
all commands of all targets ordered by send time.

The look (the tribe's template, taken from the doc "RAK Aktion Do 12.11."): A4 landscape,
Arial 10.5 pt, dark red title and headings, grey table header, fixed column widths and a coloured
"Was" cell per kind of command. Google Docs keeps inline CSS when it converts the HTML, so all
styles are inline. Change the look only here, so every operation doc looks the same.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from ap_planner.export.announce import UNIT_SHORT, TargetInfo
from ap_planner.export.review import group_by_target, is_wing, kind_label, unit_text
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand

WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
HEADER = ("Ankunft", "Abschicken", "Spieler", "Dorf", "Was", "Truppen")
COL_WIDTH_PT = (60, 105, 95, 55, 100, 325)  # sums to the usable width of A4 landscape

# --- template styles -------------------------------------------------------------------------
FONT = "font-family:Arial,sans-serif"
DARK_RED = "#7f1d1d"
GREY_TEXT = "#555555"
BORDER = "border:0.5pt solid #bbbbbb"
HEADER_BG = "#d9d9d9"
KIND_BG = {  # background of the "Was" cell
    "Off": "#fde2e1",
    "Wallbrecher": "#fde2e1",
    "AG": "#fff2cc",
    "Fake-AG": "#fbe5d6",
    "Fake": "#ededed",
    "Fake-Unterst.": "#ededed",
    "Flexdeff": "#ddebf7",
}
PAGE_CSS = "@page { size: A4 landscape; margin: 50pt; }"
BODY = f"{FONT};font-size:10.5pt;color:#000000"
TITLE = f"{FONT};font-size:22pt;font-weight:bold;color:{DARK_RED};margin:0 0 6pt 0"
SUBTITLE = f"{FONT};font-size:10.5pt;font-style:italic;color:{GREY_TEXT};margin:0"
H1 = f"{FONT};font-size:15pt;font-weight:bold;color:{DARK_RED};margin:16pt 0 6pt 0"
P = f"{FONT};font-size:10.5pt;margin:0"
NOTE = f"{FONT};font-size:10.5pt;font-style:italic;color:{GREY_TEXT};margin:0"
CELL = f"{FONT};font-size:9.5pt;{BORDER};padding:2pt 4pt;vertical-align:top"
_PLURAL = {
    "Off": "Offs",
    "AG": "AGs",
    "Fake": "Fakes",
    "Fake-AG": "Fake-AGs",
    "Flexdeff": "Flexdeff",
    "Wallbrecher": "Wallbrecher",
}
_ORDER = ("Off", "Wallbrecher", "AG", "Fake-AG", "Fake", "Flexdeff")


@dataclass(frozen=True)
class DocTarget:
    info: TargetInfo
    cmds: list[PlannedCommand]  # landing order
    show_link: str | None


def what(cmd: PlannedCommand) -> str:
    label = kind_label(cmd)
    if label in {"Unterst.", "Fake-Unterst."}:
        return "Flexdeff" if cmd.type != CommandType.FAKE_SUPPORT else "Fake-Unterst."
    return label


def player(cmd: PlannedCommand) -> str:
    name = cmd.note.split(" -> ")[0] or "?"
    return f"{name} (Wing)" if is_wing(cmd) else name


def _send_text(cmd: PlannedCommand, zone: ZoneInfo) -> str:
    if cmd.origin.endswith("manual:running"):
        return "läuft schon"
    s = cmd.send.astimezone(zone)
    return f"{WEEKDAYS[s.weekday()]} {s:%d.%m. %H:%M:%S}"


def _counts(cmds: list[PlannedCommand]) -> str:
    counts = Counter(what(c) for c in cmds)
    parts = []
    for kind in (*_ORDER, *sorted(set(counts) - set(_ORDER))):
        n = counts.get(kind, 0)
        if n:
            parts.append(f"{n} {kind if n == 1 else _PLURAL.get(kind, kind)}")
    return " · ".join(parts)


def target_role(cmds: list[PlannedCommand]) -> str:
    kinds = {what(c) for c in cmds}
    if "AG" in kinds:
        return "Adelsziel"
    if kinds & {"Off", "Wallbrecher"}:
        return "Off-Ziel"
    if kinds & {"Fake", "Fake-AG"}:
        return "Fake-Ziel"
    return "Ziel"


def setup_sentence(cmds: list[PlannedCommand], zone: ZoneInfo) -> str:
    """'Um 08:59:59 kommen 2 Offs (Suea zuerst). Um 09:00:00 kommen 4 Offs, danach 4 AGs.'"""
    by_second: dict[datetime, list[PlannedCommand]] = {}
    for c in cmds:
        by_second.setdefault(c.arrival.astimezone(zone).replace(microsecond=0), []).append(c)
    if len(by_second) > 4:  # e.g. a fake selection spread over an hour
        first, last = min(by_second), max(by_second)
        return f"Ankunft verteilt zwischen {first:%H:%M:%S} und {last:%H:%M:%S}."
    sentences = []
    for second, group in sorted(by_second.items()):
        runs: list[tuple[str, list[PlannedCommand]]] = []
        for c in group:  # already in landing order
            if runs and runs[-1][0] == what(c):
                runs[-1][1].append(c)
            else:
                runs.append((what(c), [c]))
        parts = []
        for kind, run in runs:
            n = len(run)
            text = f"{n} {kind if n == 1 else _PLURAL.get(kind, kind)}"
            if kind == "Off" and n > 1:
                text += f" ({player(run[0])} zuerst)"
            parts.append(text)
        verb = "kommt" if len(group) == 1 else "kommen"
        sentences.append(f"Um {second:%H:%M:%S} {verb} {', danach '.join(parts)}.")
    return " ".join(sentences)


def _rules(op: Operation, cmds: list[PlannedCommand], *, millis: bool) -> list[str]:
    kinds = {what(c) for c in cmds}
    rules = []
    if not millis:
        rules.append(
            "<b>Sekundengenau schicken.</b> Diese Welt hat keine Millisekunden. Was in derselben "
            "Sekunde ankommt, landet in der Reihenfolge, in der es abgeschickt wurde. Deshalb "
            "die Zeiten bitte sekundengenau einhalten."
        )
    if kinds & {"AG", "Fake-AG"}:
        rules.append(
            "<b>Reihenfolge ist entscheidend.</b> Die Offs müssen vor den AGs raus. Wer zu spät "
            "ist, bitte sofort im Discord melden, nicht einfach schicken."
        )
        escort = ", ".join(
            f"{n} {UNIT_SHORT.get(u.value, u.value) if u.value != 'axe' else 'Axt'}"
            for u, n in op.noble_settings.escort.items()
        )
        if escort:
            rules.append(
                f"<b>Begleitschutz.</b> Bei den AGs {escort} als Begleitschutz mitschicken "
                "(steht schon in den Truppen)."
            )
    if "Flexdeff" in kinds:
        rules.append(
            "<b>Flexdeff erst nach dem letzten AG.</b> Landet sie früher, verteidigt sie das Dorf "
            "des Gegners."
        )
    if op.home_guard:
        guard = ", ".join(
            f"{n} {UNIT_SHORT.get(u.value, u.value)}" for u, n in op.home_guard.items()
        )
        rules.append(f"<b>Fakeschutz.</b> {guard} bleiben überall daheim.")
    return rules


def _table(rows: list[tuple[str, ...]]) -> str:
    cols = "".join(f'<col width="{w}pt" style="width:{w}pt">' for w in COL_WIDTH_PT)
    head = "".join(
        f'<td style="{CELL};background-color:{HEADER_BG};width:{w}pt"><b>{h}</b></td>'
        for h, w in zip(HEADER, COL_WIDTH_PT, strict=True)
    )
    body = "".join(
        "<tr>" + "".join(_cell(i, cell) for i, cell in enumerate(row)) + "</tr>" for row in rows
    )
    return (
        '<table style="border-collapse:collapse;table-layout:fixed">'
        f"<colgroup>{cols}</colgroup><tr>{head}</tr>{body}</table>"
    )


def _cell(i: int, text: str) -> str:
    style = CELL
    if i == 4:  # "Was": coloured by kind ("Fake → 474|530" -> "Fake")
        bg = KIND_BG.get(text.split(" →", maxsplit=1)[0])
        if bg:
            style += f";background-color:{bg}"
    inner = f"<b>{escape(text)}</b>" if i < 2 else escape(text)
    return f'<td style="{style}">{inner}</td>'


def _row(
    c: PlannedCommand, coords: dict[int, str], zone: ZoneInfo, *, with_target: bool
) -> tuple[str, ...]:
    kind = what(c)
    if with_target:
        kind += f" → {coords.get(c.target_id, '?')}"
    return (
        f"{c.arrival.astimezone(zone):%H:%M:%S}",
        _send_text(c, zone),
        player(c),
        coords.get(c.source_id, "?"),
        kind,
        unit_text(c),
    )


def _p(text: str, style: str = P) -> str:
    return f'<p style="{style}">{text}</p>'


def _h1(text: str) -> str:
    return f'<h1 style="{H1}">{text}</h1>'


def _bullets(items: list[str]) -> str:
    return '<ul style="margin:0">' + "".join(f'<li style="{P}">{i}</li>' for i in items) + "</ul>"


def _description(op: Operation, targets: list[DocTarget]) -> list["Block"]:
    """Free text from the operation (lines starting with '- ' become bullets), else a summary."""
    if not op.beschreibung.strip():
        return [
            Bullets(
                [
                    f"<b>{target_role(t.cmds)} {escape(t.info.coord)} "
                    f"({escape(t.info.owner)}):</b> {_counts(t.cmds)}"
                    for t in targets
                ]
            )
        ]
    out: list[Block] = []
    items: list[str] = []
    for line in op.beschreibung.strip().splitlines():
        text = escape(line.strip())
        if text.startswith("- "):
            items.append(_bold_prefix(text[2:]))
            continue
        if items:
            out.append(Bullets(items))
            items = []
        if text:
            out.append(Para("p", text))
    if items:
        out.append(Bullets(items))
    return out


def _bold_prefix(text: str) -> str:
    """'**Adelsziel 481|521:** rest' -> bold part (simple Markdown bold)."""
    while text.count("**") >= 2:
        text = text.replace("**", "<b>", 1).replace("**", "</b>", 1)
    return text


@dataclass(frozen=True)
class Para:
    """One paragraph. ``html``: escaped text, may contain <b>…</b> and <a href="…">…</a>."""

    kind: str  # title, subtitle, h1, p, note
    html: str


@dataclass(frozen=True)
class Bullets:
    items: list[str]  # same mini-HTML as Para.html


@dataclass(frozen=True)
class Table:
    rows: list[tuple[str, ...]]  # plain text, without the header row


Block = Para | Bullets | Table


def operation_blocks(
    op: Operation,
    plan: Plan,
    targets: list[TargetInfo],
    coords: dict[int, str],
    tz: str,
    *,
    millis: bool = False,
    now: datetime | None = None,
) -> list[Block]:
    """Content of the operation doc, independent of the output format (HTML or Docs API)."""
    zone = ZoneInfo(tz)
    by_target = group_by_target(plan)
    docs = [
        DocTarget(
            info=t,
            cmds=by_target.get(t.village_id, []),
            show_link=(link.show_link if (link := op.dsu_link("target", t.coord)) else None),
        )
        for t in targets
    ]
    docs = [d for d in docs if d.cmds]
    everything = [c for d in docs for c in d.cmds]
    stand = (now or datetime.now(zone)).astimezone(zone)
    blocks: list[Block] = [
        Para("title", escape(op.name)),
        Para("subtitle", f"{_subtitle(docs)} · Stand {stand:%d.%m. %H:%M}"),
        Para("h1", "Worum geht es?"),
        *_description(op, docs),
        Para("h1", "Wichtig beim Abschicken"),
        Bullets(_rules(op, everything, millis=millis)),
    ]
    for d in docs:
        role = target_role(d.cmds)
        blocks.append(Para("h1", f"{role}: {escape(d.info.owner)} {escape(d.info.coord)}"))
        if role == "Fake-Ziel":
            blocks.append(Para("note", "Reihenfolge der Tabelle = Ankunft im Dorf."))
            blocks.append(
                Para("p", f"<b>{_counts(d.cmds)} · je 1 Ramme + Füller bis zum Fake-Limit</b>")
            )
        else:
            blocks.append(Para("p", f"<b>{_counts(d.cmds)}</b>"))
            blocks.append(Para("p", f"Aufbau: {escape(setup_sentence(d.cmds, zone))}"))
            blocks.append(
                Para(
                    "note",
                    "Reihenfolge der Tabelle = so landen die Befehle im Dorf (nach Ankunft; in "
                    "derselben Sekunde landet zuerst, was früher abgeschickt wurde).",
                )
            )
        if d.show_link:
            url = escape(d.show_link)
            blocks.append(Para("p", f'DS-Ultimate-Plan: <a href="{url}">{url}</a>'))
        blocks.append(Table([_row(c, coords, zone, with_target=False) for c in d.cmds]))
    if len(docs) > 1:
        blocks.append(Para("h1", "Abschick-Reihenfolge (alle Ziele)"))
        blocks.append(
            Para("p", "Zum Nachschauen der eigenen Zeit: alle Befehle nach Abschickzeit.")
        )
        ordered = sorted(everything, key=lambda c: c.send)
        blocks.append(Table([_row(c, coords, zone, with_target=True) for c in ordered]))
    return blocks


_PARA_STYLE = {"subtitle": SUBTITLE, "p": P, "note": NOTE}


def _html_block(b: Block) -> str:
    if isinstance(b, Table):
        return _table(b.rows)
    if isinstance(b, Bullets):
        return _bullets(b.items)
    if b.kind == "title":
        return f'<p style="{TITLE}">{b.html}</p>'
    if b.kind == "h1":
        return _h1(b.html)
    return _p(b.html, _PARA_STYLE[b.kind])


def operation_doc(
    op: Operation,
    plan: Plan,
    targets: list[TargetInfo],
    coords: dict[int, str],
    tz: str,
    *,
    millis: bool = False,
    now: datetime | None = None,
) -> str:
    """The doc as HTML (first upload: Google converts it into a normal Doc)."""
    blocks = operation_blocks(op, plan, targets, coords, tz, millis=millis, now=now)
    body = "\n".join(_html_block(b) for b in blocks)
    return (
        '<!DOCTYPE html>\n<html lang="de"><head><meta charset="utf-8">'
        f"<title>{escape(op.name)}</title><style>{PAGE_CSS}</style></head>"
        f'<body style="{BODY}">\n{body}\n</body></html>\n'
    )


def _subtitle(docs: list[DocTarget]) -> str:
    """'Adelsziel X 474|530 · … · Fakes auf 8 Dörfer' (fake targets summed up when many)."""
    real = [d for d in docs if target_role(d.cmds) != "Fake-Ziel"]
    fakes = [d for d in docs if target_role(d.cmds) == "Fake-Ziel"]
    parts = [f"{target_role(d.cmds)} {escape(d.info.owner)} {escape(d.info.coord)}" for d in real]
    if len(fakes) > 2:
        parts.append(f"Fakes auf {len(fakes)} weitere Dörfer")
    else:
        parts += [f"Fake-Ziel {escape(d.info.owner)} {escape(d.info.coord)}" for d in fakes]
    return " · ".join(parts)
