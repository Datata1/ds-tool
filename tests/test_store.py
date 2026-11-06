import shutil

from ap_planner.ingest.store import WorldStore
from ap_planner.models.map import Coord


def test_load_and_query(tmp_path, fixtures_dir) -> None:
    raw = tmp_path / "raw"
    shutil.copytree(fixtures_dir, raw)
    store = WorldStore(tmp_path / "w.sqlite")
    store.load_raw(raw, "de260")
    assert store.world_config().speed == 1.6
    v = store.village(1)
    assert v is not None
    assert store.village_at(Coord(x=524, y=493)) == v
    near = store.villages_in_radius(Coord(x=524, y=493), 0.5)
    assert [x.id for x in near] == [1]
    gerd = store.player_by_name("gerd")
    assert gerd is not None
    assert gerd.id == 9966
    assert store.meta("map_synced_at") is not None
