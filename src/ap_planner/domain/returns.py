"""Return trips: when do the troops of a command come home?

The way back takes as long as the way there with the same slowest unit. Survivors may be
faster (e.g. the rams died), so we also give the earliest possible return (fastest unit sent).

- Offs, wall breakers, fakes: come back.
- AGs: all but the last AG of a target come back (nobleman + escort, nobleman speed). The
  last AG conquers the village; its surviving troops stay there.
- Supports stay until they are recalled.

On worlds without ms the return gets its place in the second's order when it STARTS (impact),
not when the attack was sent - important for tabbing deff in between AGs.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from ap_planner.domain.travel import travel_seconds
from ap_planner.models.plan import CommandType, PlannedCommand
from ap_planner.models.world import WorldConfig

_SUPPORTS = (
    CommandType.SUPPORT,
    CommandType.STAND_SUPPORT,
    CommandType.FAST_SUPPORT,
    CommandType.FAKE_SUPPORT,
)


@dataclass(frozen=True)
class ReturnTrip:
    cmd: PlannedCommand
    back: datetime | None  # all survivors home (None = troops stay away)
    back_earliest: datetime | None  # if the slow units died
    note: str = ""


def _conquering(cmds: list[PlannedCommand]) -> set[int]:
    """ids (``id()``) of the last AG per target - it takes the village and stays."""
    last: dict[int, PlannedCommand] = {}
    for c in cmds:
        if c.type != CommandType.CONQUEST:
            continue
        best = last.get(c.target_id)
        if best is None or (c.arrival, c.send) > (best.arrival, best.send):
            last[c.target_id] = c
    return {id(c) for c in last.values()}


def return_trips(world: WorldConfig, cmds: list[PlannedCommand]) -> list[ReturnTrip]:
    """Return trip of every command, in the given order."""
    conquering = _conquering(cmds)
    out: list[ReturnTrip] = []
    for c in cmds:
        if c.type in _SUPPORTS:
            out.append(ReturnTrip(c, None, None, "bleibt als Unterstützung"))
            continue
        if id(c) in conquering:
            out.append(ReturnTrip(c, None, None, "erobert - Truppen bleiben im Dorf"))
            continue
        back = c.arrival + c.travel
        slow = world.unit_speed_min(c.slowest_unit)
        present = [u for u, n in c.units.items() if n > 0 and u in world.units]
        earliest = back
        if slow > 0 and present:
            fields = c.travel.total_seconds() / (slow * 60)
            fastest = min(world.unit_speed_min(u) for u in present)
            earliest = c.arrival + timedelta(seconds=travel_seconds(fields, fastest))
        out.append(ReturnTrip(c, back, earliest))
    return out
