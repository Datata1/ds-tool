"""Return times of an operation: ``rueckkehr.md`` (to read) and ``rueckkehr.json`` (for tools).

Sorted by return time, so after a train you see at a glance which villages are free again
when - for retimes and for planning the next offs / AGs.
"""

import json
from zoneinfo import ZoneInfo

from ap_planner.domain.returns import ReturnTrip, return_trips
from ap_planner.export.review import is_wing, kind_label, player_commands, unit_text
from ap_planner.models.operation import Operation
from ap_planner.models.plan import Plan, PlannedCommand
from ap_planner.models.world import WorldConfig


def plan_returns(world: WorldConfig, plan: Plan, *, fakes: bool = True) -> list[ReturnTrip]:
    """Return trips of everything that lands in this operation (ours + wing).

    ``fakes=False``: without plain fakes (a ram and some filler - not worth planning with);
    fake AGs stay, their nobleman matters for the next plan."""
    cmds = [*player_commands(plan), *(c for c in plan.existing if is_wing(c))]
    if not fakes:
        cmds = [c for c in cmds if kind_label(c) != "Fake"]
    return return_trips(world, cmds)


def _who(c: PlannedCommand) -> str:
    name = c.note.split(" -> ")[0]
    return f"{name} (Wing)" if is_wing(c) else name


def returns_markdown(
    op: Operation, trips: list[ReturnTrip], coords: dict[int, str], tz: str
) -> str:
    zone = ZoneInfo(tz)

    def co(vid: int) -> str:  # "|" would end the table cell
        return coords.get(vid, str(vid)).replace("|", "\\|")

    back = sorted((t for t in trips if t.back is not None), key=lambda t: (t.back, t.cmd.send))
    stay = [t for t in trips if t.back is None]
    lines = [
        f"# Rückkehr - {op.name}",
        "Sortiert nach Rückkehr (alle Überlebenden daheim). „frühestens“ = falls die langsamen "
        "Einheiten (Rammen, AG) sterben. Eine Rückkehr bekommt ihren Platz in der Sekunde beim "
        "Einschlag, nicht beim Abschicken.",
        "",
        "| zurück | frühestens | Spieler | Dorf | Was | Ziel | Einschlag | Einheiten |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for t in back:
        c = t.cmd
        assert t.back is not None
        early = t.back_earliest if t.back_earliest and t.back_earliest != t.back else None
        lines.append(
            f"| **{t.back.astimezone(zone):%d.%m. %H:%M:%S}** | "
            f"{f'{early.astimezone(zone):%d.%m. %H:%M:%S}' if early else '-'} | {_who(c)} | "
            f"{co(c.source_id)} | {kind_label(c)} | {co(c.target_id)} | "
            f"{c.arrival.astimezone(zone):%d.%m. %H:%M:%S} | {unit_text(c) or '-'} |"
        )
    if stay:
        lines += ["", "## Kommen nicht zurück", ""]
        lines += [
            f"- {_who(t.cmd)} {coords.get(t.cmd.source_id)} → {coords.get(t.cmd.target_id)} "
            f"({kind_label(t.cmd)}): {t.note}"
            for t in sorted(stay, key=lambda t: t.cmd.arrival)
        ]
    return "\n".join(lines) + "\n"


def returns_json(trips: list[ReturnTrip], coords: dict[int, str]) -> str:
    rows = [
        {
            "player": t.cmd.note.split(" -> ")[0],
            "wing": is_wing(t.cmd),
            "source_id": t.cmd.source_id,
            "source": coords.get(t.cmd.source_id),
            "target_id": t.cmd.target_id,
            "target": coords.get(t.cmd.target_id),
            "kind": kind_label(t.cmd),
            "send": t.cmd.send.isoformat(),
            "arrival": t.cmd.arrival.isoformat(),
            "back": t.back.isoformat() if t.back else None,
            "back_earliest": t.back_earliest.isoformat() if t.back_earliest else None,
            "units": {u.value: n for u, n in t.cmd.units.items() if n},
            "note": t.note,
        }
        for t in trips
    ]
    return json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
