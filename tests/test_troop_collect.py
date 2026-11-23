import gzip
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ap_planner import troop_collect
from ap_planner.ingest.store import WorldStore

# ally: id,name,tag,members,villages,points,all_points,rank
ALLIES = "1,Raketen,RAK,2,3,0,0,1\n2,Feind,SWRE,1,1,0,0,2\n"
# player: id,name,ally,villages,points,rank
PLAYERS = "10,Graf,1,2,0,1\n11,Suea,1,1,0,2\n20,Basol,2,1,0,3\n"
# village: id,name,x,y,player,points,rank
VILLAGES = (
    "1,A,478,535,10,5000,0\n2,B,477,533,10,3800,0\n3,C,484,530,11,9000,0\n4,D,481,521,20,4000,0\n"
)

ROW = "{name} ({coord}) K54\t5.000\t60\t30\t2368\t84\t1043\t0\t159\t33\t0\t2\t0"


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


def _paste(*coords: str) -> str:
    return "Dorf\tPunkte\n" + "\n".join(ROW.format(name="X", coord=c) for c in coords)


def test_status_tracks_who_is_missing(store: WorldStore) -> None:
    since = datetime.now(UTC) - timedelta(seconds=5)
    status = troop_collect.status(store, ["RAK"], since)
    assert [p.name for p in status.missing] == ["Graf", "Suea"]
    assert status.players[0].oldest is None

    result = troop_collect.import_paste(store, _paste("478|535", "477|533"))
    assert result.by_owner == {"Graf": 2}
    status = troop_collect.status(store, ["RAK"], since)
    assert [p.name for p in status.done] == ["Graf"]
    assert [(p.name, p.fresh, p.villages) for p in status.missing] == [("Suea", 0, 1)]

    later = datetime.now(UTC) + timedelta(seconds=1)  # older data does not count
    assert troop_collect.status(store, ["RAK"], later).done == []


def test_partial_paste_and_foreign_villages(store: WorldStore) -> None:
    since = datetime.now(UTC) - timedelta(seconds=5)
    result = troop_collect.import_paste(store, _paste("478|535", "481|521", "100|100"))
    assert result.by_owner == {"Graf": 1, "Basol": 1}
    assert [str(v.coord) for v in result.unknown] == ["100|100"]
    graf = troop_collect.status(store, ["RAK"], since).players[0]
    assert (graf.fresh, graf.villages, graf.done) == (1, 2, False)


def test_looks_like_troops() -> None:
    assert troop_collect.looks_like_troops(_paste("478|535"))
    assert not troop_collect.looks_like_troops("irgendein Text 478|535")
    assert not troop_collect.looks_like_troops("")


def test_age_text() -> None:
    now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    assert troop_collect.age_text(now - timedelta(minutes=35), now) == "35 min"
    assert troop_collect.age_text(now - timedelta(hours=5), now) == "5 h"
    assert troop_collect.age_text(now - timedelta(days=3), now) == "3 T"


class FakeClipboard:
    """Returns the given texts one after the other, then keeps the last one."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)

    def __call__(self) -> str:
        return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]


def _wait(collector: troop_collect.ClipboardCollector) -> troop_collect.CollectProgress:
    for _ in range(200):
        if not collector.running:
            break
        time.sleep(0.01)
    p = collector.snapshot()
    assert p is not None
    return p


def test_collector_imports_every_copy_until_all_are_there(tmp_path: Path, store: WorldStore):
    clip = FakeClipboard(
        _paste("484|530"),  # was in the clipboard before the start: ignored (could be old)
        _paste("478|535", "477|533"),  # Graf
        _paste("478|535", "477|533"),  # same copy again: nothing new
        "irgendein anderer Text",
        _paste("484|530"),  # Suea → everyone is there, collector stops by itself
    )
    collector = troop_collect.ClipboardCollector(
        lambda: WorldStore(tmp_path / "w.sqlite"),
        tribes=["RAK"],
        log_path=tmp_path / "truppen" / "log.txt",
        read=clip,
        interval=0.001,
    )
    collector.start(minutes=1)
    p = _wait(collector)
    assert (p.running, p.stop_reason) == (False, "alle Spieler da")
    assert p.pages == 2
    assert p.by_owner == {"Graf": 2, "Suea": 1}
    assert (tmp_path / "truppen" / "log.txt").exists()


def test_collector_stop_by_player(tmp_path: Path, store: WorldStore):
    collector = troop_collect.ClipboardCollector(
        lambda: WorldStore(tmp_path / "w.sqlite"),
        tribes=["RAK"],
        log_path=tmp_path / "log.txt",
        read=FakeClipboard("nichts"),
        interval=0.001,
    )
    collector.start(minutes=1)
    p = collector.stop("vom Spieler beendet")
    assert p is not None
    assert (p.running, p.stop_reason, p.pages) == (False, "vom Spieler beendet", 0)


def test_collector_needs_clipboard(tmp_path: Path):
    collector = troop_collect.ClipboardCollector(
        lambda: WorldStore(tmp_path / "w.sqlite"),
        tribes=[],
        log_path=tmp_path / "log.txt",
        read=lambda: None,
    )
    with pytest.raises(RuntimeError):
        collector.start(minutes=1)
