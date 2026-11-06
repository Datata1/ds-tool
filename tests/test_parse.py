from ap_planner.ingest import parse
from ap_planner.models.world import Unit, WorldConfig


def test_world_config(world: WorldConfig) -> None:
    assert world.speed == 1.6
    assert world.unit_speed == 0.625
    assert world.millis_arrival is False
    assert world.attack_gap_ms == 200
    assert world.night.active
    assert (world.night.start_hour, world.night.end_hour) == (23, 8)
    assert world.knight is False
    assert world.archer is False
    assert world.snob_max_dist == 40
    assert world.fake_limit_pct == 1.0


def test_unit_info(world: WorldConfig) -> None:
    assert world.units[Unit.RAM].speed == 30
    assert world.units[Unit.SNOB].speed == 35
    assert world.units[Unit.SNOB].pop == 100
    assert Unit.ARCHER not in world.units


def test_map_files(fixtures_dir) -> None:
    villages = parse.parse_villages((fixtures_dir / "village.txt.gz").read_bytes())
    assert villages[0].id == 1
    assert villages[0].name == "Donaustadt Dönerhaus"
    assert (villages[0].x, villages[0].y) == (524, 493)
    players = parse.parse_players((fixtures_dir / "player.txt.gz").read_bytes())
    assert players[0].name == "GERD"
    allies = parse.parse_allies((fixtures_dir / "ally.txt.gz").read_bytes())
    assert allies[0].name == "Alpen-Edelweiß"
    assert allies[0].tag == "A-E"
