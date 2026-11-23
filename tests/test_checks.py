from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ap_planner.checks import run_checks
from ap_planner.models.map import Village
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.troops import VillageTroops
from ap_planner.models.world import Unit, WorldConfig
from ap_planner.services import import_commands
from ap_planner.solver.planner import Source

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=TZ)
ARR = datetime(2026, 11, 7, 8, 15, tzinfo=TZ)
OP = Operation.model_validate(
    {"name": "t", "world": "de260", "arrival": "2026-11-07 08:15:00",
     "targets": [{"coord": "510|500", "offs": 1}]}
)  # fmt: skip


def _src(vid: int, units: dict[Unit, int]) -> Source:
    v = Village(id=vid, name="v", x=500 + vid, y=500, player_id=1, points=3000, bonus=0)
    return Source(v, f"p{vid}", VillageTroops(coord=v.coord, name="v", units=units), NOW)


def _cmd(sid: int, ctype: CommandType, units: dict[Unit, int], send_h: int) -> PlannedCommand:
    send = datetime(2026, 11, 7, send_h, 0, tzinfo=TZ)
    return PlannedCommand(
        source_id=sid, target_id=99, units=units, slowest_unit=Unit.RAM, type=ctype,
        arrival=ARR, send=send, travel=ARR - send, note=f"p{sid} -> enemy",
    )  # fmt: skip


def test_double_booking_and_missing_off(world: WorldConfig) -> None:
    src = _src(1, {Unit.SNOB: 1, Unit.AXE: 150})
    plan = Plan(
        world="de260", name="t", created_at=NOW,
        commands=[
            _cmd(1, CommandType.CONQUEST, {Unit.SNOB: 1, Unit.AXE: 100}, 6),
            _cmd(1, CommandType.CONQUEST, {Unit.SNOB: 1, Unit.AXE: 100}, 6),
        ],
    )  # fmt: skip
    rep = run_checks(OP, plan, world, [src], {99: "510|500"}, now=NOW)
    assert any("Doppelt verplant (AGs)" in e for e in rep.errors)
    assert sum("KEINE Off davor" in e for e in rep.errors) == 2


def test_clean_plan_and_free_troops(world: WorldConfig) -> None:
    off = _src(1, {Unit.AXE: 5000, Unit.LIGHT: 1000})
    ag = _src(2, {Unit.SNOB: 2, Unit.AXE: 200})
    plan = Plan(
        world="de260", name="t", created_at=NOW,
        commands=[
            _cmd(1, CommandType.ATTACK, {Unit.AXE: 5000, Unit.LIGHT: 1000}, 5),
            _cmd(2, CommandType.CONQUEST, {Unit.SNOB: 1, Unit.AXE: 100}, 6),
        ],
    )  # fmt: skip
    rep = run_checks(OP, plan, world, [off, ag], {99: "510|500"}, now=NOW)
    assert rep.errors == []
    assert any("1 AG" in f for f in rep.free)
    late = plan.model_copy(update={"commands": [
        plan.commands[0].model_copy(update={"send": ARR - timedelta(minutes=1)}),
        plan.commands[1],
    ]})  # fmt: skip
    rep2 = run_checks(OP, late, world, [off, ag], {99: "510|500"}, now=NOW)
    assert any("KEINE Off davor" in e for e in rep2.errors)


def test_running_command_is_not_late(world: WorldConfig) -> None:
    off = _src(1, {Unit.AXE: 5000, Unit.LIGHT: 1000})
    ag = _src(2, {Unit.SNOB: 1, Unit.AXE: 100})
    late_off = _cmd(1, CommandType.ATTACK, {Unit.AXE: 5000, Unit.LIGHT: 1000}, 5)
    running_ag = _cmd(2, CommandType.CONQUEST, {Unit.SNOB: 1}, 6).model_copy(
        update={"origin": "kept:manual:running"}
    )
    plan = Plan(world="de260", name="t", created_at=NOW, commands=[late_off, running_ag])
    rep = run_checks(OP, plan, world, [off, ag], {99: "510|500"}, now=NOW + timedelta(hours=19))
    late = [e for e in rep.errors if "Abschickzeit vorbei" in e]
    assert len(late) == 1
    assert "Off" in late[0]


def test_off_long_before_ag_does_not_count(world: WorldConfig) -> None:
    off = _src(1, {Unit.AXE: 5000, Unit.LIGHT: 1000})
    ag = _src(2, {Unit.SNOB: 1, Unit.AXE: 100})
    early_off = _cmd(1, CommandType.ATTACK, {Unit.AXE: 5000, Unit.LIGHT: 1000}, 5)
    noble = _cmd(2, CommandType.CONQUEST, {Unit.SNOB: 1, Unit.AXE: 100}, 6)
    for lead, ok in ((timedelta(seconds=1), True), (timedelta(minutes=20), False)):
        moved = early_off.model_copy(update={"arrival": ARR - lead})
        plan = Plan(world="de260", name="t", created_at=NOW, commands=[moved, noble])
        rep = run_checks(OP, plan, world, [off, ag], {99: "510|500"}, now=NOW)
        assert any("KEINE Off davor" in e for e in rep.errors) is not ok


def test_merge_into_existing_plan_includes_manual_attacks() -> None:
    order = Operation.model_validate(
        {"name": "t", "world": "de260", "arrival": "2026-11-07 08:15:00",
         "targets": [{"coord": "510|500", "offs": 1,
                      "dsu_plan": "https://ds-ultimate.de/tools/attackPlanner/1/edit/" + "a" * 40}]}
    ).targets[0]  # fmt: skip
    manual = _cmd(1, CommandType.ATTACK, {Unit.AXE: 100}, 1).model_copy(
        update={"origin": "kept:manual"}
    )
    old = _cmd(2, CommandType.CONQUEST, {}, 2).model_copy(update={"origin": "dsu:1"})
    new = _cmd(3, CommandType.ATTACK, {Unit.AXE: 100}, 0)
    plan = Plan(world="de260", name="t", created_at=NOW, commands=[new], existing=[manual, old])
    assert import_commands(plan, order, 99) == [new, manual]  # the plan's own rows not again
