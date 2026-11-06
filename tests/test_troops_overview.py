from pathlib import Path

from ap_planner.ingest.troops.overview_text import parse_overview_text, world_unit_columns
from ap_planner.models.map import Coord
from ap_planner.models.world import Unit, WorldConfig

PASTE = Path(__file__).parent / "fixtures" / "troops" / "overview_paste.txt"


def test_columns_for_de260(world: WorldConfig) -> None:
    assert world_unit_columns(list(world.units)) == [
        Unit.SPEAR, Unit.SWORD, Unit.AXE, Unit.SPY, Unit.LIGHT,
        Unit.HEAVY, Unit.RAM, Unit.CATAPULT, Unit.SNOB,
    ]  # fmt: skip


def test_parse_paste(world: WorldConfig) -> None:
    villages = parse_overview_text(PASTE.read_text(), world_unit_columns(list(world.units)))
    assert len(villages) == 3
    off = villages[2]
    assert off.name == "Beispieldorf C"
    assert off.coord == Coord(x=498, y=505)
    assert off.units[Unit.AXE] == 2368
    assert off.units[Unit.LIGHT] == 1043
    assert off.units[Unit.RAM] == 159
    assert off.units[Unit.SNOB] == 2
    assert off.outgoing == 2
    assert off.incoming == 0
    assert off.extra == []
    assert villages[1].units[Unit.SPEAR] == 1796


def test_several_member_pastes_concatenated(world: WorldConfig) -> None:
    text = PASTE.read_text() + "\n" + PASTE.read_text().replace("498|505", "498|506")
    villages = parse_overview_text(text, world_unit_columns(list(world.units)))
    assert len(villages) == 6
    assert villages[-1].coord == Coord(x=498, y=506)
