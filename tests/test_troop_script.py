"""Our in-game troop script: quickbar line and import of its JSON export."""

import gzip
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

from ap_planner import ingame, services, troop_collect
from ap_planner.ingest.store import WorldStore
from ap_planner.ingest.troops.script_json import parse_script_json
from ap_planner.models.world import Unit

ALLIES = "1,Raketen,RAK,2,3,0,0,1\n"
PLAYERS = "10,Graf,1,2,0,1\n11,Suea,1,1,0,2\n"
VILLAGES = "1,A,478,535,10,5000,0\n2,B,477,533,10,3800,0\n3,C,484,530,11,9000,0\n"


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


def _export(world: str = "de260", **extra: object) -> str:
    data = {
        "format": "ap-troops/1",
        "version": "1.0.0",
        "world": world,
        "created": "2026-11-23T18:00:00.000Z",
        "villages": [
            {"x": 478, "y": 535, "name": "A", "player": "Graf", "units": {"axe": 5000, "ram": 250}},
            {"x": 477, "y": 533, "name": "B", "player": "Graf", "units": {"spear": 8000}},
            {"x": 484, "y": 530, "name": "C", "player": "Suea", "units": {"snob": 2, "x": 9}},
            {"x": 484, "y": 530, "name": "C dup", "player": "Suea", "units": {"snob": 9}},
        ],
        **extra,
    }
    return json.dumps(data)


def test_parse_export() -> None:
    rows, created, world = parse_script_json(_export())
    assert world == "de260"
    assert created is not None
    assert created.isoformat().startswith("2026-11-23T18:00:00")
    assert [r.name for r in rows] == ["A", "B", "C"]  # duplicate village: first row wins
    assert rows[2].units == {Unit.SNOB: 2}  # unknown unit keys are ignored


def test_import_via_paste_and_collector(store: WorldStore) -> None:
    text = _export()
    assert troop_collect.looks_like_troops(text)
    result = troop_collect.import_paste(store, text)
    assert result.by_owner == {"Graf": 2, "Suea": 1}
    assert not result.unknown


def test_wrong_world_and_broken_text(store: WorldStore) -> None:
    with pytest.raises(ValueError, match="Welt de999"):
        services.import_overview_text(store, _export(world="de999"))
    with pytest.raises(ValueError, match="kein gültiges JSON"):
        services.import_overview_text(store, _export()[:-20])


def test_quickbar_line_is_one_valid_script() -> None:
    code = ingame.quickbar_code()
    assert code.startswith("javascript:(function")
    assert "\n" not in code
    assert "bongzilla" not in code.lower()
    body = unquote(code.removeprefix("javascript:"))
    # read-only and local: no posting anywhere, no remote code
    for forbidden in ("method:", "$.post", "$.getScript", "eval(", "XMLHttpRequest", "https://"):
        assert forbidden not in body
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    check = subprocess.run(
        [node, "--check", "-"], input=body, text=True, capture_output=True, check=False
    )
    assert check.returncode == 0, check.stderr
