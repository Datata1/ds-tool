from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ap_planner.domain import travel
from ap_planner.domain.night import in_night_bonus
from ap_planner.models.map import Coord
from ap_planner.models.world import Unit, WorldConfig

BERLIN = ZoneInfo("Europe/Berlin")


def test_distance() -> None:
    assert travel.distance(Coord(x=500, y=500), Coord(x=503, y=504)) == 5.0


@pytest.mark.parametrize(
    ("dist", "mpf", "expected"),
    [(5.0, 30, 9000), (1.0, 18, 1080), (1.41421356, 30, 2546)],
)
def test_travel_seconds(dist: float, mpf: float, expected: int) -> None:
    assert travel.travel_seconds(dist, mpf) == expected


def test_send_time(world: WorldConfig) -> None:
    arrival = datetime(2026, 11, 7, 9, 0, 0, tzinfo=BERLIN)
    send = travel.send_time(world, Coord(x=500, y=500), Coord(x=503, y=504), Unit.SNOB, arrival)
    # 5 fields * 35 min = 2h55m
    assert send == datetime(2026, 11, 7, 6, 5, 0, tzinfo=BERLIN)


def test_slowest_unit(world: WorldConfig) -> None:
    assert travel.slowest_unit(world, {Unit.AXE: 100, Unit.SNOB: 1}) == Unit.SNOB
    assert travel.slowest_unit(world, {Unit.AXE: 100, Unit.LIGHT: 5, Unit.RAM: 0}) == Unit.AXE


@pytest.mark.parametrize(("hour", "expected"), [(22, False), (23, True), (3, True), (8, False)])
def test_night_bonus(world: WorldConfig, hour: int, expected: bool) -> None:
    when = datetime(2026, 11, 7, hour, 30, tzinfo=BERLIN)
    assert in_night_bonus(world.night, when) is expected
