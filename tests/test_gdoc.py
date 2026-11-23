import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ap_planner import services
from ap_planner.export.announce import TargetInfo
from ap_planner.export.gdoc import HEADER, Bullets, Para, Table, operation_doc, setup_sentence
from ap_planner.export.gdoc_api import rewrite_requests
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit

TZ = ZoneInfo("Europe/Berlin")


def _plain(html: str) -> str:
    """HTML without the inline styles, for content checks."""
    return re.sub(r' style="[^"]*"', "", html)


T0 = datetime(2026, 11, 12, 9, 0, 0, tzinfo=TZ)


def _cmd(src: int, kind: CommandType, arrival: datetime, travel_h: float, who: str, **units: int):
    return PlannedCommand(
        source_id=src,
        target_id=9,
        units={Unit(u): n for u, n in units.items()},
        slowest_unit=Unit.SNOB if kind == CommandType.CONQUEST else Unit.RAM,
        type=kind,
        arrival=arrival,
        send=arrival - timedelta(hours=travel_h),
        travel=timedelta(hours=travel_h),
        note=f"{who} -> X",
    )


def _plan() -> Plan:
    one_s = timedelta(seconds=1)
    cmds = [
        _cmd(1, CommandType.ATTACK, T0 - one_s, 5, "Suea", axe=5153, ram=279),
        _cmd(2, CommandType.ATTACK, T0 - one_s, 4, "Pls", axe=1554, ram=79),
        _cmd(3, CommandType.ATTACK, T0, 9, "Rette", axe=1952, ram=108),
        _cmd(4, CommandType.CONQUEST, T0, 6, "Suea", snob=1, axe=100),
        _cmd(5, CommandType.SUPPORT, T0 + one_s, 3, "Graf", spear=2966),
    ]
    return Plan.model_validate(
        {"world": "de260", "name": "Test", "created_at": datetime.now(UTC), "commands": cmds}
    )


def _op(**extra: object) -> Operation:
    data = {
        "name": "RAK Aktion",
        "world": "de260",
        "arrival": "2026-11-12 09:00:00",
        "targets": [{"coord": "481|521", "offs": 3, "nobles": 1}],
        "noble_settings": {"escort": {"axe": 100}},
    }
    return Operation.model_validate({**data, **extra})


def test_setup_sentence_follows_landing_order() -> None:
    cmds = sorted(_plan().commands, key=lambda c: (c.arrival, c.send))
    text = setup_sentence(cmds, TZ)
    assert text == (
        "Um 08:59:59 kommen 2 Offs (Suea zuerst). "
        "Um 09:00:00 kommen 1 Off, danach 1 AG. Um 09:00:01 kommt 1 Flexdeff."
    )


def test_doc_has_sections_tables_and_rules() -> None:
    show = "https://ds-ultimate.de/tools/attackPlanner/1/show/abc"
    op = _op(dsu_links=[{"kind": "target", "key": "481|521", "show_link": show}])
    info = TargetInfo("481|521", 9, "Dorf", "fgrockstar", "SWRE")
    coords = {1: "484|530", 2: "483|529", 3: "497|538", 4: "484|530", 5: "477|533", 9: "481|521"}
    html = _plain(operation_doc(op, _plan(), [info], coords, "Europe/Berlin", now=T0))
    assert "<h1>Adelsziel: fgrockstar 481|521</h1>" in html
    assert "<b>3 Offs · 1 AG · 1 Flexdeff</b>" in html
    assert "100 Axt als Begleitschutz" in html
    assert "keine Millisekunden" in html
    assert show in html
    assert "<td><b>Do 12.11. 00:00:00</b></td>" in html  # Rette: 9 h before 09:00
    assert "/edit/" not in html
    # landing order: same second = send order (Suea leaves before Pls)
    assert html.index("5153 Axt") < html.index("1554 Axt") < html.index("1952 Axt")


def test_beschreibung_becomes_bullets() -> None:
    op = _op(beschreibung="RAKK adelt.\n- **Adelsziel:** fgrockstar\n- Fakes auf Basol")
    info = TargetInfo("481|521", 9, "Dorf", "fgrockstar", "SWRE")
    html = _plain(operation_doc(op, _plan(), [info], {}, "Europe/Berlin", now=T0))
    html = html.replace("\n", "")
    assert "<p>RAKK adelt.</p><ul><li><b>Adelsziel:</b> fgrockstar</li>" in html


def test_parse_gdoc_id() -> None:
    doc_id = "1oCwJf7bBdI-Z9OOk_ReFwsunJtOJwQctu_9LFr_GN1Y"
    assert services.parse_gdoc_id(f"https://docs.google.com/document/d/{doc_id}/edit") == doc_id
    assert services.parse_gdoc_id(doc_id) == doc_id


def test_doc_uses_the_template_style() -> None:
    info = TargetInfo("481|521", 9, "Dorf", "fgrockstar", "SWRE")
    html = operation_doc(_op(), _plan(), [info], {}, "Europe/Berlin", now=T0)
    assert "size: A4 landscape" in html
    assert "background-color:#d9d9d9" in html  # table header
    assert 'background-color:#fde2e1">Off<' in html  # Off red
    assert 'background-color:#fff2cc">AG<' in html  # AG yellow
    assert 'background-color:#ddebf7">Flexdeff<' in html  # Flexdeff blue
    assert "color:#7f1d1d" in html  # dark red headings


def test_doc_update_requests_follow_the_docs_index_rules() -> None:
    row = ("09:00:00", "Mo 16.11. 03:00:00", "Bobby", "486|509", "Off", "100 Axt")
    reqs = rewrite_requests(
        [Para("title", "Ä"), Bullets(["<b>a</b> b"]), Table([row]), Para("h1", "x")], 296
    )
    assert reqs[0] == {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 295}}}
    inserts = [r["insertText"] for r in reqs if "insertText" in r]
    assert inserts[0] == {"location": {"index": 1}, "text": "Ä\n"}
    [table] = [r["insertTable"] for r in reqs if "insertTable" in r]
    at = table["location"]["index"]
    assert at == 1 + 2 + 4  # "Ä\n" + "a b\n"
    # cells are filled from the last to the first: first cell = table start + 3
    cells = [i for i in inserts[:-1] if i["location"]["index"] > at]
    assert cells[-1] == {"location": {"index": at + 4}, "text": "Ankunft"}
    # next paragraph right after the table (verified against the live API: table end + 1)
    filled = sum(len(t) for t in (*HEADER, *row))
    assert inserts[-1]["location"]["index"] == at + 1 + 1 + 2 * 13 + filled + 1
