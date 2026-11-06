"""Distance and travel-time math.

Tribal Wars computes the runtime as ``distance * minutes_per_field`` and rounds
to whole seconds. ``minutes_per_field`` from ``get_unit_info`` already includes
world speed and unit speed. Worlds without ms control (``millis_arrival = 0``)
only let us plan at second granularity.
"""

import math
from collections.abc import Mapping
from datetime import datetime, timedelta

from ap_planner.models.map import Coord
from ap_planner.models.world import Unit, WorldConfig


def distance(a: Coord, b: Coord) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def travel_seconds(dist: float, minutes_per_field: float) -> int:
    """Runtime in whole seconds, rounded half-up like the game does."""
    return math.floor(dist * minutes_per_field * 60 + 0.5)


def travel_time(world: WorldConfig, a: Coord, b: Coord, unit: Unit) -> timedelta:
    return timedelta(seconds=travel_seconds(distance(a, b), world.unit_speed_min(unit)))


def send_time(world: WorldConfig, a: Coord, b: Coord, unit: Unit, arrival: datetime) -> datetime:
    return arrival - travel_time(world, a, b, unit)


def slowest_unit(world: WorldConfig, units: Mapping[Unit, int]) -> Unit:
    """The unit that determines the speed of a command (largest minutes/field)."""
    present = [u for u, n in units.items() if n > 0]
    if not present:
        msg = "A command needs at least one unit."
        raise ValueError(msg)
    return max(present, key=world.unit_speed_min)
