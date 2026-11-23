"""Create and fill DS Ultimate attack plans without an API key.

Uses exactly the requests the DS Ultimate web page itself sends from the browser
(see ds-ultimatev2 ``routes/tools.php`` and ``AttackPlannerController``):

- ``GET  /tools/create/attackPlanner/{server}/{world}`` creates a plan and redirects to
  its edit link,
- ``POST /tools/attackPlanner/{id}/importWB/{edit_key}`` imports workbench text,
- ``POST /tools/attackPlanner/{id}/title/{edit_key}/{title}`` sets the title,
- ``POST /tools/attackPlanner/{id}/clear/{edit_key}`` removes all attacks (link stays).

Only DS Ultimate is contacted, never the game. One request at a time with a short pause.
"""

import re
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from ap_planner.dsu import DSU_BASE, DsuLinkError, parse_link
from ap_planner.ingest.world_client import USER_AGENT

_CSRF_RE = re.compile(r'<meta\s+name="csrf-token"\s+content="([^"]+)"')
# DS Ultimate's own browser import sends small batches; stay well below any limit.
IMPORT_CHUNK = 200


class DsuWebError(RuntimeError):
    """DS Ultimate refused a request or answered unexpectedly."""


@dataclass(frozen=True)
class EditablePlan:
    plan_id: int
    edit_key: str

    @property
    def edit_link(self) -> str:
        return f"{DSU_BASE}/tools/attackPlanner/{self.plan_id}/edit/{self.edit_key}"

    @classmethod
    def from_link(cls, link: str) -> "EditablePlan":
        plan_id, mode, key = parse_link(link)
        if mode != "edit":
            msg = "Zum Ändern wird der Bearbeiten-Link (…/edit/…) gebraucht."
            raise DsuLinkError(msg)
        return cls(plan_id, key)


def safe_title(title: str) -> str:
    """DS Ultimate takes the title as a URL path segment: no slashes, no line breaks."""
    return re.sub(r"[/\\\r\n]+", "-", title).strip()[:190]


class DsuWebClient:
    def __init__(self, client: httpx.Client | None = None, pause: float = 1.0) -> None:
        self._client = client or httpx.Client(
            base_url=DSU_BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )
        self._pause = pause
        self._csrf: str | None = None

    def close(self) -> None:
        self._client.close()

    def _wait(self) -> None:
        if self._pause:
            time.sleep(self._pause)

    def _token(self, plan: EditablePlan) -> str:
        """CSRF token of the browser session (one per session, read from the edit page)."""
        if self._csrf is None:
            page = self._client.get(f"/tools/attackPlanner/{plan.plan_id}/edit/{plan.edit_key}")
            if page.status_code == 403:
                msg = "DS Ultimate sagt 'nicht erlaubt' - der Bearbeiten-Schlüssel stimmt nicht."
                raise DsuWebError(msg)
            page.raise_for_status()
            m = _CSRF_RE.search(page.text)
            if m is None:
                msg = "DS Ultimate hat die Seite geändert (kein CSRF-Token) - bitte --manuell."
                raise DsuWebError(msg)
            self._csrf = m[1]
            self._wait()
        return self._csrf

    def _post(
        self, plan: EditablePlan, path: str, json: dict[str, str] | None = None
    ) -> httpx.Response:
        r = self._client.post(
            path,
            json=json or {},
            headers={
                "X-CSRF-TOKEN": self._token(plan),
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
            },
        )
        self._wait()
        if r.status_code == 403:
            msg = "DS Ultimate sagt 'nicht erlaubt' - der Bearbeiten-Schlüssel stimmt nicht."
            raise DsuWebError(msg)
        if r.status_code == 419:
            msg = "DS Ultimate: Sitzung abgelaufen (CSRF). Bitte nochmal starten."
            raise DsuWebError(msg)
        if r.status_code >= 400:
            msg = f"DS Ultimate antwortet mit Fehler {r.status_code}."
            raise DsuWebError(msg)
        return r

    def create(self, world: str) -> EditablePlan:
        """Create a new empty plan for a world like 'de260'."""
        m = re.fullmatch(r"([a-z]+)(\w+)", world)
        if m is None:
            msg = f"Unbekanntes Weltformat: {world}"
            raise ValueError(msg)
        r = self._client.get(f"/tools/create/attackPlanner/{m[1]}/{m[2]}")
        self._wait()
        r.raise_for_status()
        try:
            plan = EditablePlan.from_link(str(r.url))
        except DsuLinkError as err:
            msg = f"DS Ultimate hat keinen neuen Plan angelegt (Antwort: {r.url})."
            raise DsuWebError(msg) from err
        m_csrf = _CSRF_RE.search(r.text)
        if m_csrf is not None:
            self._csrf = m_csrf[1]
        return plan

    def set_title(self, plan: EditablePlan, title: str) -> None:
        t = quote(safe_title(title), safe="")
        self._post(plan, f"/tools/attackPlanner/{plan.plan_id}/title/{plan.edit_key}/{t}")

    def import_workbench(self, plan: EditablePlan, text: str) -> None:
        lines = [x for x in text.splitlines() if x.strip()]
        for i in range(0, len(lines), IMPORT_CHUNK):
            chunk = "\n".join(lines[i : i + IMPORT_CHUNK])
            r = self._post(
                plan,
                f"/tools/attackPlanner/{plan.plan_id}/importWB/{plan.edit_key}",
                {"import": chunk},
            )
            try:
                data = r.json()
            except ValueError as err:
                msg = "DS Ultimate hat den Import nicht bestätigt (keine JSON-Antwort)."
                raise DsuWebError(msg) from err
            if data.get("data") != "success":
                detail = data.get("msg") or data
                msg = f"Workbench-Import fehlgeschlagen: {detail}"
                raise DsuWebError(msg)

    def clear(self, plan: EditablePlan) -> None:
        """Remove every attack from the plan. Title and links stay the same."""
        self._post(plan, f"/tools/attackPlanner/{plan.plan_id}/clear/{plan.edit_key}")
