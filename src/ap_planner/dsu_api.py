"""Official DS Ultimate attack planner API (``/toolAPI/attackPlanner/*``, needs an API key).

Mirrors ds-ultimatev2 ``AttackPlannerAPIController``:

- ``create``: new plan with title (and up to 1050 items) in one request
- ``createItems``: add items to a plan (needs its edit key)
- ``clear``: remove all items, the links stay the same
- ``destroyOutdated``: remove items whose send time is over
- ``fetch``: read items, including ``send`` (the player ticked "verschickt" in DS Ultimate)

Item format: ``arrival_time`` = Unix seconds, ``ms`` = milliseconds, ``slowest_unit`` = index
into DSU_UNITS, ``type`` = DS Ultimate icon id, unit counts by unit name. The key is personal
(DS Ultimate logs every request per key): never share it, never put it into the extension.
Only DS Ultimate is contacted, never the game.
"""

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from ap_planner.dsu import DSU_BASE, DSU_UNITS, DsuPlanInfo, parse_link
from ap_planner.dsu_web import EditablePlan
from ap_planner.ingest.world_client import USER_AGENT
from ap_planner.models.plan import PlannedCommand

# DS Ultimate refuses more than 1050 items per request.
API_CHUNK = 1000
_ERRORS = {
    403: "DS Ultimate: API-Key ungültig oder falscher Bearbeiten-Link.",
    404: "DS Ultimate: Plan oder Welt nicht gefunden.",
    422: "DS Ultimate: Daten abgelehnt.",
    503: "DS Ultimate: Welt ist gerade in Wartung, bitte später nochmal.",
}


class DsuApiError(RuntimeError):
    """DS Ultimate refused an API request."""


def api_item(cmd: PlannedCommand) -> dict[str, Any]:
    """One planned command in the API format (see module doc)."""
    arrival_ms = round(cmd.arrival.timestamp() * 1000)
    item: dict[str, Any] = {
        "source": cmd.source_id,
        "destination": cmd.target_id,
        "type": int(cmd.type),
        "slowest_unit": DSU_UNITS.index(cmd.slowest_unit),
        "arrival_time": arrival_ms // 1000,
        "ms": arrival_ms % 1000,
    }
    for unit in DSU_UNITS:
        item[unit.value] = cmd.units.get(unit, 0)
    return item


@dataclass(frozen=True)
class ApiItem:
    """One attack as DS Ultimate stores it (from ``fetch``)."""

    source_id: int
    target_id: int
    arrival: datetime
    send_time: datetime
    sent: bool  # ticked as "verschickt" in DS Ultimate

    @classmethod
    def from_json(cls, it: dict[str, Any]) -> "ApiItem":
        return cls(
            source_id=int(it["source"]),
            target_id=int(it["destination"]),
            arrival=datetime.fromtimestamp(int(it["arrival_time"]), UTC),
            send_time=datetime.fromtimestamp(int(it["send_time"]), UTC),
            sent=bool(it.get("send")),
        )


class DsuApiClient:
    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        pause: float = 0.5,
    ) -> None:
        if not api_key:
            msg = "Kein DS-Ultimate-API-Key eingetragen."
            raise DsuApiError(msg)
        self._key = api_key
        self._client = client or httpx.Client(
            base_url=DSU_BASE,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=60.0,
        )
        self._sleep = sleep
        self._pause = pause

    def close(self) -> None:
        self._client.close()

    def _post(self, action: str, data: dict[str, Any]) -> dict[str, Any]:
        r = self._client.post(
            f"/toolAPI/attackPlanner/{action}", json={"API_KEY": self._key, **data}
        )
        self._sleep(self._pause)  # one request at a time, with a short pause
        if r.status_code >= 400:
            detail = ""
            try:
                body = r.json()
                detail = str(body.get("message") or body.get("errors") or "")
            except ValueError:
                pass
            msg = _ERRORS.get(r.status_code, f"DS Ultimate: Fehler {r.status_code}")
            raise DsuApiError(f"{msg} {detail}".strip())
        result = r.json()
        if errors := result.get("errors"):
            msg = f"DS Ultimate meldet: {'; '.join(map(str, errors))}"
            raise DsuApiError(msg)
        return result

    def create(self, world: str, title: str, commands: Iterable[PlannedCommand]) -> DsuPlanInfo:
        """New plan with title and all commands. ``world`` like "de260"."""
        m = re.fullmatch(r"([a-z]+)(\w+)", world)
        if m is None:
            msg = f"Unbekanntes Weltformat: {world}"
            raise DsuApiError(msg)
        server, number = m[1], m[2]
        items = [api_item(c) for c in commands]
        res = self._post(
            "create",
            {"title": title, "server": server, "world": number, "items": items[:API_CHUNK]},
        )
        target = EditablePlan(int(res["id"]), str(res["edit_key"]))
        for start in range(API_CHUNK, len(items), API_CHUNK):
            self._add(target, items[start : start + API_CHUNK])
        return DsuPlanInfo(int(res["id"]), str(res["edit"]), str(res["show"]), title, len(items))

    def _add(self, target: EditablePlan, items: list[dict[str, Any]]) -> None:
        self._post(
            "createItems", {"id": target.plan_id, "edit_key": target.edit_key, "items": items}
        )

    def add(self, target: EditablePlan, commands: Iterable[PlannedCommand]) -> int:
        """Add commands to an existing plan; returns how many were sent."""
        items = [api_item(c) for c in commands]
        for start in range(0, len(items), API_CHUNK):
            self._add(target, items[start : start + API_CHUNK])
        return len(items)

    def clear(self, target: EditablePlan) -> None:
        self._post("clear", {"id": target.plan_id, "edit_key": target.edit_key})

    def destroy_outdated(self, target: EditablePlan) -> None:
        self._post("destroyOutdated", {"id": target.plan_id, "edit_key": target.edit_key})

    def fetch(self, link: str) -> tuple[str, list[ApiItem]]:
        """Title and all items of a plan (edit or show link)."""
        plan_id, mode, key = parse_link(link)
        auth = {"edit_key": key} if mode == "edit" else {"show_key": key}
        items: list[ApiItem] = []
        title = ""
        while True:
            res = self._post(
                "fetch", {"id": plan_id, **auth, "start": len(items), "length": API_CHUNK}
            )
            title = str(res.get("title") or "")
            page = res.get("items") or []
            items += [ApiItem.from_json(it) for it in page]
            if len(page) < API_CHUNK:
                return title, items
