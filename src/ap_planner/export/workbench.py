"""DS-Workbench line format, accepted by DS Ultimate's "Import Workbench" box.

Format (one command per line), mirrored from ds-ultimatev2's ``exportWB``::

    src&target&slowestUnit&arrivalEpochMs&typeId&false&false&spear=<b64>/sword=<b64>/.../militia=MA==

Unit counts are base64-encoded decimal strings. Arrival is a real Unix epoch
in milliseconds.
"""

import base64
from collections.abc import Iterable

from ap_planner.models.plan import PlannedCommand
from ap_planner.models.world import Unit

WB_UNITS: tuple[Unit, ...] = (
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


def _b64(n: int) -> str:
    return base64.b64encode(str(n).encode()).decode()


def to_workbench_line(cmd: PlannedCommand) -> str:
    arrival_ms = round(cmd.arrival.timestamp() * 1000)
    units = "/".join(f"{u.value}={_b64(cmd.units.get(u, 0))}" for u in WB_UNITS)
    return (
        f"{cmd.source_id}&{cmd.target_id}&{cmd.slowest_unit.value}&{arrival_ms}"
        f"&{int(cmd.type)}&false&false&{units}"
    )


def to_workbench(commands: Iterable[PlannedCommand]) -> str:
    return "\n".join(to_workbench_line(c) for c in commands) + "\n"
