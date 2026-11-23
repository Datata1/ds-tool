"""The Google Doc is the projection of the latest plan: created once, reused, shared, linked."""

import gzip
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ap_planner import services
from ap_planner.export.announce import discord_review
from ap_planner.ingest.store import WorldStore
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit

TZ = "Europe/Berlin"
ALLIES = "1,Raketen,RAK,2,3,0,0,1\n2,Feind,SWRE,1,1,0,0,2\n"
PLAYERS = "10,Graf,1,2,0,1\n11,Suea,1,1,0,2\n20,Basol,2,1,0,3\n"
VILLAGES = "1,A,478,535,10,5000,0\n3,C,484,530,11,9000,0\n4,D,481,521,20,4000,0\n"
T0 = datetime(2026, 11, 12, 9, 0, 0, tzinfo=ZoneInfo(TZ))
DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


@pytest.fixture
def store(tmp_path: Path, fixtures_dir: Path) -> WorldStore:
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("config.xml", "units.xml"):
        shutil.copy(fixtures_dir / name, raw / name)
    for name, text in (("ally", ALLIES), ("player", PLAYERS), ("village", VILLAGES)):
        (raw / f"{name}.txt.gz").write_bytes(gzip.compress(text.encode()))
    s = WorldStore(tmp_path / "w.sqlite")
    s.load_raw(raw, "de260")
    return s


def _plan(axe: int = 5000) -> Plan:
    cmd = PlannedCommand(
        source_id=1,
        target_id=4,
        units={Unit.AXE: axe, Unit.RAM: 200},
        slowest_unit=Unit.RAM,
        type=CommandType.ATTACK,
        arrival=T0,
        send=T0 - timedelta(hours=3),
        travel=timedelta(hours=3),
        note="Graf -> D",
    )
    return Plan.model_validate(
        {"world": "de260", "name": "Test", "created_at": datetime.now(UTC), "commands": [cmd]}
    )


@pytest.fixture
def op_path(tmp_path: Path) -> Path:
    folder = tmp_path / "ops" / "test"
    folder.mkdir(parents=True)
    op = Operation.model_validate(
        {
            "name": "RAK Aktion",
            "world": "de260",
            "arrival": "2026-11-12 09:00:00",
            "targets": [{"coord": "481|521", "offs": 1}],
        }
    )
    path = folder / "operation.yaml"
    services.save_operation(op, path)
    (folder / "plan.json").write_text(_plan().model_dump_json(), encoding="utf-8")
    return path


def _state(store: WorldStore, path: Path) -> services.GdocState:
    op, plan = services.load_operation(path), services.load_plan(path)
    return services.gdoc_state(store, op, plan, TZ)


def test_first_plan_needs_a_doc(store: WorldStore, op_path: Path) -> None:
    state = _state(store, op_path)
    assert state.status == "fehlt"
    assert not state.ready
    assert state.view_link is None


def test_doc_created_shared_then_outdated_by_plan_change(store: WorldStore, op_path: Path) -> None:
    services.mark_gdoc(store, op_path, TZ, doc_id=DOC_ID)
    state = _state(store, op_path)
    assert (state.status, state.geteilt, state.ready) == ("aktuell", False, False)

    services.mark_gdoc(store, op_path, TZ, geteilt=True)
    state = _state(store, op_path)
    assert state.ready
    assert state.view_link == f"https://docs.google.com/document/d/{DOC_ID}/view"

    # re-planned: same doc, but it no longer shows the latest plan
    (op_path.parent / "plan.json").write_text(_plan(axe=6000).model_dump_json(), "utf-8")
    state = _state(store, op_path)
    assert (state.status, state.geteilt) == ("veraltet", True)

    # rewritten in place -> current again, id and sharing kept
    op = services.mark_gdoc(store, op_path, TZ)
    assert op.gdoc_id == DOC_ID
    assert _state(store, op_path).ready


def test_fingerprint_ignores_stand_time(store: WorldStore, op_path: Path) -> None:
    op, plan = services.load_operation(op_path), services.load_plan(op_path)
    a = services.doc_fingerprint(store, op, plan, TZ)
    b = services.doc_fingerprint(store, op, plan, TZ)
    assert a == b
    changed = op.model_copy(update={"beschreibung": "Neu: zweite Welle"})
    assert services.doc_fingerprint(store, changed, plan, TZ) != a


def test_new_doc_id_resets_sharing(store: WorldStore, op_path: Path) -> None:
    services.mark_gdoc(store, op_path, TZ, doc_id=DOC_ID, geteilt=True)
    other = "9ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210"
    op = services.mark_gdoc(store, op_path, TZ, doc_id=other)
    assert (op.gdoc_id, op.gdoc_geteilt) == (other, False)


def test_review_links_the_shared_doc(store: WorldStore, op_path: Path) -> None:
    plan = services.load_plan(op_path)
    op = services.mark_gdoc(store, op_path, TZ, doc_id=DOC_ID)
    infos = services.target_infos(store, op)
    assert "docs.google.com" not in discord_review(op, plan, infos, TZ)  # not shared yet
    op = services.mark_gdoc(store, op_path, TZ, geteilt=True)
    text = discord_review(op, plan, infos, TZ)
    assert f"<https://docs.google.com/document/d/{DOC_ID}/view>" in text
    assert "/edit" not in text
