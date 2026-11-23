import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from ap_planner import services
from ap_planner.dsu import DsuClient, DsuPlanInfo
from ap_planner.dsu_web import DsuWebClient, DsuWebError, EditablePlan, safe_title
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, PlannedCommand
from ap_planner.models.world import Unit

BASE = "https://ds-ultimate.de"
KEY_E = "e" * 40
KEY_S = "S" * 40
EDIT = f"{BASE}/tools/attackPlanner/77/edit/{KEY_E}"
SHOW = f"{BASE}/tools/attackPlanner/77/show/{KEY_S}"
PAGE = '<head><meta name="csrf-token" content="tok123"></head>'


def _cmd(source: int = 1) -> PlannedCommand:
    arrival = datetime(2026, 11, 7, 9, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    return PlannedCommand(
        source_id=source,
        target_id=2,
        units={Unit.AXE: 6000, Unit.RAM: 300},
        slowest_unit=Unit.RAM,
        type=CommandType.ATTACK,
        arrival=arrival,
        send=arrival - timedelta(hours=2),
        travel=timedelta(hours=2),
    )


def _op() -> Operation:
    return Operation.model_validate(
        {
            "name": "t",
            "world": "de260",
            "arrival": "2026-11-07 09:00:00",
            "targets": [{"coord": "510|500", "offs": 1}],
        }
    )


@respx.mock
def test_create_title_import_clear() -> None:
    respx.get(f"{BASE}/tools/create/attackPlanner/de/260").mock(
        return_value=httpx.Response(302, headers={"Location": EDIT})
    )
    respx.get(EDIT).mock(return_value=httpx.Response(200, text=PAGE))
    title = respx.post(url__regex=r".*/attackPlanner/77/title/e+/.*").mock(
        return_value=httpx.Response(200)
    )
    imp = respx.post(f"{BASE}/tools/attackPlanner/77/importWB/{KEY_E}").mock(
        return_value=httpx.Response(200, json={"data": "success"})
    )
    clear = respx.post(f"{BASE}/tools/attackPlanner/77/clear/{KEY_E}").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    web = DsuWebClient(pause=0)
    plan = web.create("de260")
    assert plan == EditablePlan(77, KEY_E)
    web.set_title(plan, "ADELN 07.11. | Ziel 481|532 A/B")
    assert str(title.calls.last.request.url).endswith(
        "ADELN%2007.11.%20%7C%20Ziel%20481%7C532%20A-B"
    )
    assert title.calls.last.request.headers["X-CSRF-TOKEN"] == "tok123"
    web.import_workbench(plan, "a\nb\n\n")
    assert json.loads(imp.calls.last.request.content) == {"import": "a\nb"}
    web.clear(plan)
    assert clear.called


@respx.mock
def test_import_error_is_reported() -> None:
    respx.get(EDIT).mock(return_value=httpx.Response(200, text=PAGE))
    respx.post(f"{BASE}/tools/attackPlanner/77/importWB/{KEY_E}").mock(
        return_value=httpx.Response(200, json={"data": "error", "msg": "falsche Daten"})
    )
    with pytest.raises(DsuWebError, match="falsche Daten"):
        DsuWebClient(pause=0).import_workbench(EditablePlan(77, KEY_E), "x")


@respx.mock
def test_import_is_chunked() -> None:
    respx.get(EDIT).mock(return_value=httpx.Response(200, text=PAGE))
    imp = respx.post(f"{BASE}/tools/attackPlanner/77/importWB/{KEY_E}").mock(
        return_value=httpx.Response(200, json={"data": "success"})
    )
    DsuWebClient(pause=0).import_workbench(
        EditablePlan(77, KEY_E), "\n".join(str(i) for i in range(450))
    )
    assert imp.call_count == 3


def test_safe_title() -> None:
    assert safe_title("a/b\\c\nd") == "a-b-c-d"


class FakeWeb(DsuWebClient):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create(self, world: str) -> EditablePlan:
        self.calls.append("create")
        return EditablePlan(77, KEY_E)

    def set_title(self, plan: EditablePlan, title: str) -> None:
        self.calls.append(f"title:{title}")

    def import_workbench(self, plan: EditablePlan, text: str) -> None:
        self.calls.append(f"import:{len(text.splitlines())}")

    def clear(self, plan: EditablePlan) -> None:
        self.calls.append("clear")


class FakeReader(DsuClient):
    def __init__(self, count: int, title: str = "OFF | Ziel") -> None:
        self.count, self.title = count, title

    def inspect(self, link: str) -> DsuPlanInfo:
        return DsuPlanInfo(77, EDIT, SHOW, self.title, self.count)


def test_publish_creates_and_saves_link() -> None:
    group = services.DsuGroup("target", "510|500", "OFF | Ziel", [_cmd(1), _cmd(3)])
    web = FakeWeb()
    op, res = services.publish_dsu_group(web, FakeReader(2), _op(), group)
    assert web.calls == ["create", "title:OFF | Ziel", "import:2"]
    assert res.action == "angelegt"
    assert not res.problems
    link = op.dsu_link("target", "510|500")
    assert link is not None
    assert link.show_link == SHOW
    assert link.edit_link == EDIT


def test_publish_update_clears_same_plan() -> None:
    group = services.DsuGroup("target", "510|500", "OFF | Ziel", [_cmd(1)])
    web = FakeWeb()
    op, _ = services.publish_dsu_group(web, FakeReader(1), _op(), group)
    web.calls.clear()
    op, res = services.publish_dsu_group(web, FakeReader(1), op, group, update=True)
    assert web.calls[0] == "clear"
    assert "create" not in web.calls
    assert res.action == "aktualisiert"
    assert len(op.dsu_links) == 1


def test_publish_reports_wrong_count_but_keeps_link() -> None:
    group = services.DsuGroup("target", "510|500", "OFF | Ziel", [_cmd(1), _cmd(3)])
    op, res = services.publish_dsu_group(FakeWeb(), FakeReader(5), _op(), group)
    assert res.problems
    assert "5 Angriffe" in res.problems[0]
    assert op.dsu_link("target", "510|500") is not None
