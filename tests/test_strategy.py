"""Strategy advisor: next targets for our troops, readel advantage."""

import gzip
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ap_planner import services
from ap_planner.domain import strategy
from ap_planner.ingest.store import WorldStore
from ap_planner.models.map import Coord
from ap_planner.models.profile import Profile
from ap_planner.models.troops import TroopSnapshot, VillageTroops
from ap_planner.models.world import Unit

ALLIES = "1,Raketen,RAK,2,3,0,0,1\n2,Feind,SWRE,1,3,0,0,2\n"
PLAYERS = "10,Graf,1,2,90000,1\n11,Suea,1,1,90000,2\n20,Basol,2,3,60000,3\n"
# ours: A, B (Graf), C (Suea); enemy: D near us, E far away, F next to D (re-noble source)
VILLAGES = (
    "1,A,500,500,10,9000,0\n2,B,502,500,10,9000,0\n3,C,501,503,11,9000,0\n"
    "4,D,506,500,20,8000,0\n5,E,560,560,20,8000,0\n6,F,515,500,20,8000,0\n"
)


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
    rows = [
        VillageTroops(coord=Coord(x=500, y=500), name="A",
                      units={Unit.AXE: 6000, Unit.RAM: 300, Unit.SNOB: 2}),
        VillageTroops(coord=Coord(x=502, y=500), name="B",
                      units={Unit.SPEAR: 5000, Unit.SWORD: 5000}),
        VillageTroops(coord=Coord(x=501, y=503), name="C",
                      units={Unit.AXE: 5000, Unit.LIGHT: 500, Unit.RAM: 200}),
    ]  # fmt: skip
    s.save_troops(TroopSnapshot(source="test", captured_at=datetime.now(UTC), villages=rows))
    return s


def _profile() -> Profile:
    return Profile(world="de260", own_tribes=["RAK"])


def test_ranks_reachable_targets_with_readel_advantage(store: WorldStore) -> None:
    ranked, own = services.strategy_targets(store, _profile(), "SWRE", max_hours=12)
    assert own == 3
    coords = [str(s.village.coord) for s in ranked]
    assert coords[0] == "506|500"  # closest, enemy re-noble source F is 9 fields away
    best = ranked[0]
    assert best.ag is not None
    assert best.ag.coord == "500|500"
    assert best.nobles_in_range == 2
    assert best.offs_in_range == 2  # A and C are full offs
    assert best.deff is not None
    assert best.deff.coord == "502|500"
    assert best.readel_margin_s is not None
    assert best.readel_margin_s > 0  # our deff (4 fields) beats their noble (9 fields)
    assert "560|560" not in coords  # too far for our nobles


def test_player_as_enemy_and_unknown_enemy(store: WorldStore) -> None:
    ranked, _ = services.strategy_targets(store, _profile(), "Basol", max_hours=12)
    assert ranked
    with pytest.raises(LookupError):
        services.strategy_targets(store, _profile(), "Niemand")


def test_needs_profile_tribe_and_troops(store: WorldStore) -> None:
    with pytest.raises(ValueError, match="own_tribes"):
        services.strategy_targets(store, Profile(world="de260"), "SWRE")
    with pytest.raises(ValueError, match="Truppen"):
        services.strategy_targets(store, Profile(world="de260", own_tribes=["SWRE"]), "RAK")


def test_negative_margin_scores_lower(store: WorldStore) -> None:
    world = store.world_config()
    own = services.own_villages(store, ["RAK"])
    near = services.strategy_candidates(store, "SWRE")
    target = next(c for c in near if c.village.id == 4)
    # pretend the enemy has a village right next to the target
    close_enemy = target.village.model_copy(update={"id": 99, "x": 507})
    pressured = strategy.Candidate(
        target.village, target.owner, target.tribe, target.owner_points, [close_enemy]
    )
    kwargs = {"max_seconds": 12 * 3600, "off_min_pop": 3000, "deff_min_pop": 2000}
    safe = strategy.score_target(world, target, own, **kwargs)
    risky = strategy.score_target(world, pressured, own, **kwargs)
    assert risky.readel_margin_s is not None
    assert risky.readel_margin_s < 0
    assert risky.score < safe.score
