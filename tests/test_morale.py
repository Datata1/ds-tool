import shutil
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ap_planner.checks import run_checks
from ap_planner.domain.morale import attack_blocked, morale_pct, ratio_protected
from ap_planner.ingest.store import WorldStore
from ap_planner.models.map import Village
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.profile import Profile
from ap_planner.models.troops import VillageTroops
from ap_planner.models.world import Unit, WorldConfig
from ap_planner.services import player_joined, ratio_protected_players
from ap_planner.solver.planner import Source, Target, plan_operation

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=TZ)
ARR = datetime(2026, 11, 7, 12, 0, tzinfo=TZ)
OFF = {Unit.AXE: 5000, Unit.LIGHT: 2000, Unit.RAM: 250}


def _w(world: WorldConfig) -> WorldConfig:
    return world.model_copy(update={"moral": 3, "newbie_ratio": 10, "newbie_ratio_days": 60})


def test_morale_formula(world: WorldConfig) -> None:
    w = _w(world)
    assert morale_pct(w, 10_000, 10_000) == 100
    assert morale_pct(w, 35_230, 4_503) == 68  # 3 * 4503 / 35230 + 0.3
    assert morale_pct(w, 100_000, 1_000) == 32
    assert morale_pct(w, 1_000_000, 1_000) == 30  # never below 30 %
    assert morale_pct(w, 35_230, 0) == 100  # barbarian
    assert morale_pct(w.model_copy(update={"moral": 0}), 100_000, 1_000) == 100


def test_ratio_rule(world: WorldConfig) -> None:
    w = _w(world)
    assert attack_blocked(w, 50_000, 4_000, active=True)
    assert attack_blocked(w, 4_000, 50_000, active=True)  # both directions
    assert not attack_blocked(w, 40_000, 4_000, active=True)  # exactly 10:1 is ok
    assert not attack_blocked(w, 50_000, 0, active=True)  # barbarian
    assert not attack_blocked(w, 50_000, 4_000, active=False)
    assert ratio_protected(w, None, NOW)  # unknown start: assume protection
    assert ratio_protected(w, date(2026, 10, 1), NOW)
    assert not ratio_protected(w, date(2026, 8, 1), NOW)


def _src(vid: int, x: int, points: int, units: dict[Unit, int]) -> Source:
    v = Village(id=vid, name="v", x=x, y=500, player_id=vid, points=3000, bonus=0)
    troops = VillageTroops(coord=v.coord, name="v", units=units)
    return Source(v, f"p{vid}", troops, NOW, player_points=points)


def _op(**target: object) -> Operation:
    return Operation.model_validate(
        {"name": "t", "world": "de260", "arrival": "2026-11-07 12:00:00",
         "send_window": {"start": "00:00", "end": "23:59:59"},
         "off_settings": {"min_pop": 7000},
         "targets": [{"coord": "510|500", **target}]}
    )  # fmt: skip


def _target(op: Operation, points: int) -> Target:
    v = Village(id=99, name="t", x=510, y=500, player_id=50, points=4000, bonus=0)
    return Target(op.targets[0], v, "enemy", owner_points=points)


def test_planner_skips_blocked_and_weak_offs(world: WorldConfig) -> None:
    w = _w(world)
    op = _op(offs=1, fakes=1)
    huge = _src(1, 509, 60_000, {**OFF, Unit.SPEAR: 100})  # closest, but 12:1 -> blocked
    big = _src(2, 508, 30_000, OFF)  # closer, but only 80 % morale
    small = _src(3, 505, 5_000, OFF)
    res = plan_operation(op, w, [huge, big, small], [_target(op, 5_000)], now=NOW,
                         ratio_protected=frozenset({"p1", "p2", "p3"}))  # fmt: skip
    assert {c.source_id for c in res.plan.commands} >= {3}
    assert all(c.source_id != 1 for c in res.plan.commands)
    [off] = [c for c in res.plan.commands if c.type == CommandType.ATTACK]
    assert off.source_id == 3  # full morale beats the closer, weaker big attacker
    assert any("Punkteverhältnis" in w for w in res.plan.warnings)


def test_check_reports_ratio_and_morale(world: WorldConfig) -> None:
    w = _w(world)
    op = _op(offs=1)

    def cmd(sid: int, ctype: CommandType, units: dict[Unit, int]) -> PlannedCommand:
        send = datetime(2026, 11, 7, 6, 0, tzinfo=TZ)
        return PlannedCommand(
            source_id=sid, target_id=99, units=units, slowest_unit=Unit.RAM, type=ctype,
            arrival=ARR, send=send, travel=ARR - send, note=f"p{sid} -> enemy",
        )  # fmt: skip

    plan = Plan(
        world="de260", name="t", created_at=NOW,
        commands=[cmd(1, CommandType.ATTACK, OFF), cmd(2, CommandType.FAKE, {Unit.RAM: 1})],
    )  # fmt: skip
    points = {1: ("big", 35_230), 2: ("huge", 60_000), 99: ("enemy", 4_503)}
    rep = run_checks(op, plan, w, [], {99: "510|500"}, now=NOW, points=points,
                     ratio_protected=frozenset({"huge", "big"}))  # fmt: skip
    assert any("huge" in e and "13.3:1" in e for e in rep.errors)
    assert any("Moral 68 %" in x and "big" in x for x in rep.warnings)


def test_join_date_per_account(tmp_path, fixtures_dir, world: WorldConfig) -> None:
    raw = tmp_path / "raw"
    shutil.copytree(fixtures_dir, raw)
    store = WorldStore(tmp_path / "w.sqlite")
    store.load_raw(raw, "de260")
    w = _w(world)
    # seen at the first sync -> joined before: world start counts
    assert player_joined(store, None, "gerd") is None
    profile = Profile(world="de260", world_start=date(2026, 8, 1))
    assert player_joined(store, profile, "gerd") == date(2026, 8, 1)
    assert ratio_protected_players(store, w, profile, ["gerd", "Barbar"], NOW) == frozenset()
    # joined later (first seen after our first sync) -> own 60 days
    with store.conn:
        store.conn.execute("UPDATE meta SET value = '2026-10-01T00:00:00+00:00' "
                           "WHERE key = 'tracking_since'")  # fmt: skip
        store.conn.execute("UPDATE player_first_seen SET first_seen = '2026-10-20T10:00:00+00:00'")
    assert player_joined(store, profile, "gerd") == date(2026, 10, 20)
    assert ratio_protected_players(store, w, profile, ["gerd"], NOW) == {"gerd"}
    # hand-entered date wins
    profile.player_joined["Gerd"] = date(2026, 1, 1)
    assert ratio_protected_players(store, w, profile, ["gerd"], NOW) == frozenset()
