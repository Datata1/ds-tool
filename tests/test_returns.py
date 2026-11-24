from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ap_planner.domain.returns import return_trips
from ap_planner.export.returns import plan_returns, returns_json, returns_markdown
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit, WorldConfig

TZ = ZoneInfo("Europe/Berlin")
ARR = datetime(2026, 11, 16, 9, 28, 0, tzinfo=TZ)


def _cmd(sid: int, ctype: CommandType, units: dict[Unit, int], slowest: Unit, minutes: int, *,
         arrival: datetime = ARR) -> PlannedCommand:  # fmt: skip
    travel = timedelta(minutes=minutes)
    return PlannedCommand(
        source_id=sid, target_id=99, units=units, slowest_unit=slowest, type=ctype,
        arrival=arrival, send=arrival - travel, travel=travel, note=f"p{sid} -> enemy",
    )  # fmt: skip


def test_return_rules(world: WorldConfig) -> None:
    # de260 fixture: ram 30, snob 35, axe 18, light 10 min/field
    off = _cmd(
        1, CommandType.ATTACK, {Unit.AXE: 3000, Unit.LIGHT: 1000, Unit.RAM: 200}, Unit.RAM, 150
    )  # fmt: skip  (5 fields)
    ag1 = _cmd(2, CommandType.CONQUEST, {Unit.SNOB: 1, Unit.AXE: 100}, Unit.SNOB, 70)
    ag2 = _cmd(3, CommandType.CONQUEST, {Unit.SNOB: 1, Unit.AXE: 100}, Unit.SNOB, 35)
    sup = _cmd(4, CommandType.SUPPORT, {Unit.SPEAR: 1000}, Unit.SPEAR, 36,
               arrival=ARR + timedelta(seconds=1))  # fmt: skip
    t_off, t_ag1, t_ag2, t_sup = return_trips(world, [off, ag1, ag2, sup])
    assert t_off.back == ARR + timedelta(minutes=150)
    assert t_off.back_earliest == ARR + timedelta(minutes=50)  # only light cavalry survived
    assert t_ag1.back == ARR + timedelta(minutes=70)  # first AG returns at noble speed
    assert t_ag1.back_earliest == ARR + timedelta(minutes=36)  # nobleman died: escort only
    assert t_ag2.back is None  # the last AG conquers, its troops stay
    assert "erobert" in t_ag2.note
    assert t_sup.back is None


def test_returns_outputs(world: WorldConfig) -> None:
    off = _cmd(1, CommandType.ATTACK, {Unit.AXE: 3000, Unit.RAM: 200}, Unit.RAM, 150)
    ag = _cmd(2, CommandType.CONQUEST, {Unit.SNOB: 1, Unit.AXE: 100}, Unit.SNOB, 70)
    trips = return_trips(world, [off, ag])
    op = Operation.model_validate(
        {"name": "Op", "world": "de260", "arrival": "2026-11-16 09:28:00",
         "targets": [{"coord": "510|500", "offs": 1}]}
    )  # fmt: skip
    coords = {1: "500|500", 2: "508|500", 99: "510|500"}
    md = returns_markdown(op, trips, coords, "Europe/Berlin")
    assert "| **16.11. 11:58:00** | 16.11. 10:58:00 | p1 | 500\\|500 | Off | 510\\|500 |" in md
    assert "p2 508|500 → 510|500 (AG): erobert" in md
    assert '"back": "2026-11-16T11:58:00+01:00"' in returns_json(trips, coords)


def test_plan_returns_can_skip_plain_fakes(world: WorldConfig) -> None:
    off = _cmd(1, CommandType.ATTACK, {Unit.AXE: 3000, Unit.RAM: 200}, Unit.RAM, 150)
    fake = _cmd(2, CommandType.FAKE, {Unit.RAM: 1, Unit.SPEAR: 40}, Unit.RAM, 150)
    fake_ag = _cmd(3, CommandType.FAKE, {Unit.SNOB: 1, Unit.AXE: 100}, Unit.SNOB, 70)
    plan = Plan(world="de260", name="Op", created_at=ARR, commands=[off, fake, fake_ag])
    assert len(plan_returns(world, plan)) == 3  # conflict checks still see the fakes
    shown = plan_returns(world, plan, fakes=False)
    assert [t.cmd.source_id for t in shown] == [1, 3]  # fake AG stays: its noble matters
