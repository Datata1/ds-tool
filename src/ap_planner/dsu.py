"""Read-only checks against DS Ultimate attack plans the user created.

Only the user's own plans are read, via the edit/show keys they paste. Nothing is
created or changed here, and this module never talks to the game itself.
"""

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import unquote_plus
from zoneinfo import ZoneInfo

import httpx

from ap_planner.ingest.world_client import USER_AGENT
from ap_planner.models.plan import CommandType, PlannedCommand
from ap_planner.models.world import Unit

DSU_BASE = "https://ds-ultimate.de"
LINK_RE = re.compile(
    r"https://(?:www\.)?ds-ultimate\.de/tools/attackPlanner/(?P<id>\d+)/(?P<mode>edit|show)/"
    r"(?P<key>[A-Za-z0-9]{40})(?![A-Za-z0-9])"
)
NO_TITLE = {"", "Kein Titel", "No title"}
# Unit index order used by DS Ultimate (AttackListItem::$units).
DSU_UNITS: tuple[Unit, ...] = (
    Unit.SPEAR, Unit.SWORD, Unit.AXE, Unit.ARCHER, Unit.SPY, Unit.LIGHT,
    Unit.MARCHER, Unit.HEAVY, Unit.RAM, Unit.CATAPULT, Unit.KNIGHT, Unit.SNOB,
)  # fmt: skip
_VILLAGE_ID = re.compile(r"/village/(\d+)")
_DT_COLUMNS = ("start_village_id", "target_village_id", "slowest_unit", "type", "send_time")


class DsuLinkError(ValueError):
    """The pasted link is not a usable DS Ultimate plan link."""


@dataclass(frozen=True)
class DsuPlanInfo:
    plan_id: int
    edit_link: str | None
    show_link: str
    title: str
    item_count: int

    @property
    def has_title(self) -> bool:
        return self.title.strip() not in NO_TITLE


def parse_link(text: str) -> tuple[int, str, str]:
    """Return (plan_id, mode, key) from a pasted DS Ultimate link."""
    m = LINK_RE.search(text.strip())
    if m is None:
        msg = (
            "Kein vollständiger DS-Ultimate-Link. Erwartet: "
            "https://ds-ultimate.de/tools/attackPlanner/<id>/edit/<40 Zeichen>"
        )
        raise DsuLinkError(msg)
    return int(m["id"]), m["mode"], m["key"]


class DsuClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url=DSU_BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def _data(self, plan_id: int, show_key: str, start: int, length: int) -> dict[str, Any]:
        """One page of the DataTables endpoint behind the show page."""
        params = {"draw": "1", "start": str(start), "length": str(length)}
        params |= {"search[value]": "", "search[regex]": "false"}
        for i, col in enumerate(_DT_COLUMNS):
            params |= {
                f"columns[{i}][data]": col,
                f"columns[{i}][name]": col,
                f"columns[{i}][searchable]": "true",
                f"columns[{i}][orderable]": "true",
                f"columns[{i}][search][value]": "",
                f"columns[{i}][search][regex]": "false",
            }
        r = self._client.get(
            f"/tools/attackPlanner/attackListItem/data/{plan_id}/{show_key}",
            params=params,
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        r.raise_for_status()
        return r.json()

    def item_count(self, plan_id: int, show_key: str) -> int:
        """Number of attacks in a plan."""
        return int(self._data(plan_id, show_key, 0, 1)["recordsTotal"])

    def commands(self, link: str, tz: str = "Europe/Berlin") -> list[PlannedCommand]:
        """All attacks of an existing plan (read-only), as fixed commands."""
        info = self.inspect(link)
        _, _, show_key = parse_link(info.show_link)
        rows: list[dict[str, Any]] = []
        while len(rows) < info.item_count:
            page = self._data(info.plan_id, show_key, len(rows), 200)["data"]
            if not page:
                break
            rows += page
        return [row_to_command(r, info.plan_id, ZoneInfo(tz)) for r in rows]

    def inspect(self, link: str) -> DsuPlanInfo:
        plan_id, mode, key = parse_link(link)
        page = self._client.get(f"/tools/attackPlanner/{plan_id}/{mode}/{key}")
        if page.status_code == 403:
            msg = "DS Ultimate sagt 'nicht erlaubt' - der Schlüssel im Link stimmt nicht."
            raise DsuLinkError(msg)
        page.raise_for_status()
        title_m = re.search(r'id="title-show"[^>]*>([^<]*)<', page.text)
        title = html.unescape(title_m[1]).strip() if title_m else ""
        if mode == "edit":
            show_m = re.search(r'id="link-show"[^>]*value="([^"]+)"', page.text)
            if show_m is None:
                msg = "Ansehen-Link auf der Bearbeiten-Seite nicht gefunden."
                raise DsuLinkError(msg)
            show_link = html.unescape(show_m[1])
            edit_link = f"{DSU_BASE}/tools/attackPlanner/{plan_id}/edit/{key}"
        else:
            show_link, edit_link = f"{DSU_BASE}/tools/attackPlanner/{plan_id}/show/{key}", None
        _, _, show_key = parse_link(show_link)
        return DsuPlanInfo(plan_id, edit_link, show_link, title, self.item_count(plan_id, show_key))


def row_to_command(row: dict[str, Any], plan_id: int, tz: ZoneInfo) -> PlannedCommand:
    """Convert one DataTables row of a DS Ultimate plan into a fixed command."""
    data = row["DT_RowData"]

    def village_id(cell: str) -> int:
        m = _VILLAGE_ID.search(cell or "")
        if m is None:
            msg = f"Dorf-ID nicht gefunden in {cell!r}"
            raise ValueError(msg)
        return int(m[1])

    def local(day: str, clock: str) -> datetime:
        return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=tz)

    arrival = local(data["day"], data["time"])
    send = local(data["sday"], data["stime"])
    try:
        ctype = CommandType(int(data["type"]))
    except ValueError:
        ctype = CommandType.NONE
    attacker = unquote_plus(row.get("start_village__playerLatest__name") or "?")
    defender = unquote_plus(row.get("target_village__playerLatest__name") or "?")
    units = {u: int(row.get(u.value) or 0) for u in DSU_UNITS if int(row.get(u.value) or 0)}
    return PlannedCommand(
        source_id=village_id(row["start_village_id"]),
        target_id=village_id(row["target_village_id"]),
        source_player_id=row.get("start_village__owner"),
        units=units,
        slowest_unit=DSU_UNITS[int(data["slowest_unit"])],
        type=ctype,
        arrival=arrival,
        send=send,
        travel=max(arrival - send, timedelta(0)),
        note=f"{attacker} -> {defender}",
        origin=f"dsu:{plan_id}",
    )
