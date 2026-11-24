"""Parser for the export of our own in-game quickbar script (``scripts/ingame/truppen.js``).

The player runs the script himself in the game (Stamm → Mitglieder → Truppen). It reads the
troop pages of all members that share their troops and shows one JSON text to copy::

    {"format": "ap-troops/1", "world": "de260", "created": "2026-11-23T18:00:00Z",
     "villages": [{"x": 478, "y": 535, "name": "A", "player": "Graf",
                   "units": {"spear": 60, "axe": 2368, ...}}]}

Nothing is fetched here: we only read what the player pasted or copied.
"""

import json
from datetime import UTC, datetime
from typing import Any

from ap_planner.ingest.store import MAX_UNITS
from ap_planner.models.map import Coord
from ap_planner.models.troops import VillageTroops
from ap_planner.models.world import Unit

FORMAT = "ap-troops/1"


def looks_like_script_json(text: str) -> bool:
    """Cheap check: a JSON object that names our format."""
    s = text.strip()
    return s.startswith("{") and f'"{FORMAT}"' in s[:200]


def _units(raw: dict[str, Any]) -> dict[Unit, int] | None:
    """Unit counts, or None if the row is implausible (e.g. a misread column)."""
    known = {u.value for u in Unit}
    out: dict[Unit, int] = {}
    for key, value in raw.items():
        if key not in known:
            continue
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            return None
        if n < 0 or n > MAX_UNITS:
            return None
        out[Unit(key)] = n
    return out


def parse_script_json(text: str) -> tuple[list[VillageTroops], datetime | None, str | None]:
    """Villages, creation time and world from the script export. Raises ValueError if broken."""
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError as err:
        msg = f"Skript-Export ist kein gültiges JSON (unvollständig kopiert?): {err.msg}"
        raise ValueError(msg) from err
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        msg = f"Unbekanntes Format - erwartet '{FORMAT}' vom ap-planner-Skript."
        raise ValueError(msg)
    villages: dict[tuple[int, int], VillageTroops] = {}
    skipped: list[str] = []
    for row in data.get("villages") or []:
        try:
            coord = Coord(x=int(row["x"]), y=int(row["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        key = (coord.x, coord.y)
        if key in villages:  # the same village twice: keep the first row
            continue
        units = _units(row.get("units") or {})
        if units is None:
            skipped.append(f"{coord.x}|{coord.y}")
            continue
        villages[key] = VillageTroops(coord=coord, name=str(row.get("name") or ""), units=units)
    created: datetime | None = None
    if isinstance(data.get("created"), str):
        try:
            created = datetime.fromisoformat(data["created"].replace("Z", "+00:00"))
        except ValueError:
            created = None
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
    world = data.get("world") if isinstance(data.get("world"), str) else None
    if skipped and not villages:
        msg = f"Skript-Export unlesbar (unplausible Werte bei {', '.join(skipped[:5])})."
        raise ValueError(msg)
    return list(villages.values()), created, world
