"""``aktion.md``: the one Discord-ready post for the current operation(s), always the same layout.

Per operation: header (name, status, description, Google Doc), "Pläne pro Dorf" (one line per
target plan) and "Pläne pro Spieler" (one line per player plan). Links are DS Ultimate
**edit** links on purpose (the tribe leader works with them); this file is never posted to
players directly. Messages are split below Discord's 2000 characters.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ap_planner.export.announce import TargetInfo, split_discord
from ap_planner.export.review import group_by_target, kind_label, player_commands
from ap_planner.models.operation import Operation, Status
from ap_planner.models.plan import CommandType, Plan, PlannedCommand

SEPARATOR = "✂️ ───── neue Nachricht ───── ✂️"
DISCORD_LIMIT = 1900  # a little room below 2000
_WEEKDAY = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
_FAKES = (CommandType.FAKE, CommandType.FAKE_SUPPORT)
_COUNT_ORDER = (
    ("Off", "Off", "Offs"),
    ("Wallbrecher", "Wallbrecher", "Wallbrecher"),
    ("AG", "AG", "AGs"),
    ("Unterst.", "Flexdeff", "Flexdeff"),
    ("Fake-AG", "Fake-AG", "Fake-AGs"),
    ("Fake", "Fake", "Fakes"),
    ("Fake-Unterst.", "Fake-Unterstützung", "Fake-Unterstützungen"),
)


@dataclass(frozen=True)
class AktionOp:
    op: Operation
    plan: Plan
    targets: list[TargetInfo]


def _player(c: PlannedCommand) -> str:
    return c.note.split(" -> ")[0]


def _day(dt: datetime) -> str:
    return f"{_WEEKDAY[dt.weekday()]} {dt:%d.%m.}"


def _counts(cmds: list[PlannedCommand]) -> str:
    """'3 Offs, 5 AGs, 2 Fakes' in a fixed order."""
    kinds = Counter(kind_label(c) for c in cmds)
    return ", ".join(
        f"{kinds[k]} {one if kinds[k] == 1 else many}"
        for k, one, many in _COUNT_ORDER
        if kinds.get(k)
    )


def _who(cmds: list[PlannedCommand]) -> str:
    """'Knödelprinzessin, Bobby Glass, 3× Intmeister07' in landing order."""
    counts = Counter(_player(c) for c in cmds)
    return ", ".join(f"{n}× {p}" if n > 1 else p for p, n in counts.items())


def _edit(url: str | None) -> str:
    # <...>: no link preview in Discord
    return f"<{url}>" if url else "⚠️ kein Bearbeiten-Link gespeichert"


def _arrivals(cmds: list[PlannedCommand], zone: ZoneInfo) -> str:
    real = [c for c in cmds if c.type not in _FAKES] or cmds
    seconds = sorted({c.arrival.astimezone(zone).replace(microsecond=0) for c in real})
    if len(seconds) > 3:
        return f"{seconds[0]:%H:%M:%S}–{seconds[-1]:%H:%M:%S}"
    return " / ".join(f"{s:%H:%M:%S}" for s in seconds)


def _plan_label(title: str, cmds: list[PlannedCommand]) -> str:
    """ADELN / OFF / FAKE: from the DS Ultimate title, else from the commands."""
    words = title.split("|", 1)[0].split(maxsplit=1)
    head = words[0].upper() if words else ""
    if head.isalpha():
        return head
    if any(c.type == CommandType.CONQUEST for c in cmds):
        return "ADELN"
    if any(c.type in (CommandType.ATTACK, CommandType.WALLBREAKER) for c in cmds):
        return "OFF"
    return "FAKE"


def _target_lines(a: AktionOp, zone: ZoneInfo) -> list[str]:
    by_target = group_by_target(a.plan)
    lines: list[tuple[datetime, str]] = []
    for t in a.targets:
        link = a.op.dsu_link("target", t.coord)
        if link is None or "ENTFÄLLT" in link.title.upper():
            continue
        cmds = by_target.get(t.village_id, [])
        if not cmds:
            continue
        label = _plan_label(link.title, cmds)
        line = f"- **{label} {_arrivals(cmds, zone)}** {t.coord} ({t.owner})"
        nobles = [c for c in cmds if c.type == CommandType.CONQUEST]
        if nobles:
            line += f" → geht an **{_player(nobles[-1])}**"
        line += f" · {_counts(cmds)}"
        if nobles:
            line += f" ({_who(nobles)})"
        landing = min(c.arrival for c in [c for c in cmds if c.type not in _FAKES] or cmds)
        lines.append((landing, f"{line}: {_edit(link.edit_link)}"))
    return [line for _, line in sorted(lines, key=lambda x: x[0])]


def _time_range(cmds: list[PlannedCommand], zone: ZoneInfo) -> str:
    first = min(c.send for c in cmds).astimezone(zone)
    last = max(c.send for c in cmds).astimezone(zone)
    if len(cmds) == 1 or first == last:
        return f"{_day(first)} {first:%H:%M:%S}"
    if first.date() == last.date():
        return f"{_day(first)} {first:%H:%M:%S}–{last:%H:%M:%S}"
    return f"{_day(first)} {first:%H:%M:%S} bis {_day(last)} {last:%H:%M:%S}"


def _player_lines(a: AktionOp, zone: ZoneInfo) -> list[str]:
    groups: dict[str, list[PlannedCommand]] = {}
    for c in sorted(player_commands(a.plan), key=lambda c: c.send):
        groups.setdefault(_player(c), []).append(c)
    lines: list[str] = []
    for player, cmds in groups.items():  # ordered by first send time
        link = a.op.dsu_link("player", player)
        lines.append(
            f"- {player} ({_counts(cmds)}, {_time_range(cmds, zone)}): "
            f"{_edit(link.edit_link if link else None)}"
        )
    return lines


def _header(a: AktionOp, zone: ZoneInfo) -> str:
    op = a.op
    status = "" if op.status == Status.APPROVED else " (Review)"
    real = [c for c in [*player_commands(a.plan), *a.plan.existing] if c.type not in _FAKES]
    when = real or player_commands(a.plan)
    day = _day(min(c.arrival for c in when).astimezone(zone)) if when else ""
    lines = [f"**{op.name}**{status}" + (f" – Einschlag {day}" if day else "")]
    if op.beschreibung.strip():
        lines.append(op.beschreibung.strip())
    if op.gdoc_id:
        lines.append(f"📄 Doc: <https://docs.google.com/document/d/{op.gdoc_id}/edit>")
    return "\n".join(lines)


def aktion_messages(ops: list[AktionOp], tz: str) -> list[str]:
    """All Discord messages of aktion.md, each below the Discord limit."""
    zone = ZoneInfo(tz)
    messages: list[str] = []
    for a in ops:
        targets = _target_lines(a, zone)
        players = _player_lines(a, zone)
        first = [_header(a, zone)]
        if targets:
            first.append("**Pläne pro Dorf (SF)**\n" + "\n".join(targets))
        messages += split_discord("\n\n".join(first), DISCORD_LIMIT)
        if players:
            text = (
                "**Pläne pro Spieler** – bitte nur euren eigenen Plan öffnen und alles "
                f"sekundengenau schicken ({a.op.name})\n" + "\n".join(players)
            )
            messages += split_discord(text, DISCORD_LIMIT)
    return messages


def aktion_markdown(ops: list[AktionOp], tz: str) -> str:
    return f"\n\n{SEPARATOR}\n\n".join(aktion_messages(ops, tz)) + "\n"
