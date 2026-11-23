"""Parser for text copied from Übersichten → Truppen (Ctrl+A / Ctrl+C).

The unit icons in the header are images, so the copied text has no unit names.
Columns are mapped by position using the world's unit order. Any extra trailing
columns are outgoing commands and incoming attacks; anything beyond that is
kept in ``VillageTroops.extra``.

Example row (tab-separated)::

    Sankt Korngrund (478|535) K54\t4.614\t60\t30\t2368\t84\t1043\t0\t159\t33\t2\t2\t0

Ctrl+A also copies the page header, which shows the village you are in, e.g.
``Mein Dorf (480|529) K45``. It has the same ``Name (x|y) Kxx`` shape but no unit counts, so
only rows with a number for every unit column count as troop rows. Otherwise the header
would overwrite the real troops of that village with zeros.
"""

import re
from collections.abc import Sequence

from ap_planner.models.map import Coord
from ap_planner.models.troops import VillageTroops
from ap_planner.models.world import Unit

ROW_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<x>\d{1,3})\|(?P<y>\d{1,3})\)\s*K\d+\s*(?P<rest>.*)$")
# Game order of units; the world's available units are a subsequence of this.
GAME_UNIT_ORDER: tuple[Unit, ...] = (
    Unit.SPEAR,
    Unit.SWORD,
    Unit.AXE,
    Unit.ARCHER,
    Unit.SPY,
    Unit.LIGHT,
    Unit.MARCHER,
    Unit.HEAVY,
    Unit.RAM,
    Unit.CATAPULT,
    Unit.KNIGHT,
    Unit.SNOB,
    Unit.MILITIA,
)


def world_unit_columns(available: Sequence[Unit]) -> list[Unit]:
    """Columns as shown in the overview for a world with the given units."""
    present = set(available)
    return [u for u in GAME_UNIT_ORDER if u in present and u != Unit.MILITIA]


def _to_int(cell: str) -> int:
    return int(cell.replace(".", "").replace(",", "").strip() or 0)


def parse_overview_text(
    text: str, columns: Sequence[Unit], *, has_points: bool = True
) -> list[VillageTroops]:
    villages: list[VillageTroops] = []
    for raw_line in text.splitlines():
        m = ROW_RE.match(raw_line.strip())
        if m is None:
            continue
        cells = [c for c in re.split(r"\t+|\s{2,}", m["rest"].strip()) if c.strip()]
        numbers = [_to_int(c) for c in cells if re.fullmatch(r"[\d.,]+", c.strip())]
        if has_points and numbers:
            numbers = numbers[1:]
        if len(numbers) < len(columns):
            continue  # page header (current village) or a broken row, not a table row
        units = dict(zip(columns, numbers, strict=False))
        trailing = numbers[len(columns) :]
        villages.append(
            VillageTroops(
                coord=Coord(x=int(m["x"]), y=int(m["y"])),
                name=m["name"].strip(),
                units=units,
                outgoing=trailing[0] if len(trailing) > 0 else 0,
                incoming=trailing[1] if len(trailing) > 1 else 0,
                extra=trailing[2:],
            )
        )
    return villages
