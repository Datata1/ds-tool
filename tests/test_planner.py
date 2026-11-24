from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from ap_planner.models.map import Village
from ap_planner.models.operation import Operation, SendWindow
from ap_planner.models.plan import CommandType, PlannedCommand
from ap_planner.models.troops import VillageTroops
from ap_planner.models.world import Unit, WorldConfig
from ap_planner.solver.planner import Source, Target, plan_operation

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=TZ)


def _village(vid: int, x: int, y: int, player: int = 1, points: int = 5000) -> Village:
    return Village(id=vid, name=f"v{vid}", x=x, y=y, player_id=player, points=points, bonus=0)


def _source(vid: int, x: int, y: int, units: dict[Unit, int]) -> Source:
    v = _village(vid, x, y)
    return Source(v, f"p{vid}", VillageTroops(coord=v.coord, name=v.name, units=units), NOW)


OFF = {Unit.AXE: 5000, Unit.LIGHT: 2000, Unit.RAM: 250, Unit.SPEAR: 100}


def _op(**target: object) -> Operation:
    return Operation.model_validate(
        {
            "name": "t",
            "world": "de260",
            "arrival": "2026-11-07 12:00:00",
            "send_window": {"start": "00:00", "end": "23:59:59"},
            "noble_settings": {"escort": {"axe": 100}},
            "targets": [{"coord": "510|500", **target}],
        }
    )


def _target(op: Operation) -> Target:
    return Target(op.targets[0], _village(99, 510, 500, player=2), "enemy")


def test_picks_closest_off(world: WorldConfig) -> None:
    sources = [_source(1, 500, 500, OFF), _source(2, 505, 500, OFF)]
    op = _op(offs=1)
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    [cmd] = res.plan.commands
    assert cmd.source_id == 2
    assert cmd.type == CommandType.ATTACK
    assert cmd.slowest_unit == Unit.RAM
    assert cmd.travel == timedelta(minutes=150)  # 5 fields * 30 min
    assert cmd.arrival == datetime(2026, 11, 7, 12, 0, tzinfo=TZ)
    assert res.shortfalls == []


def test_excluded_player_sends_no_off(world: WorldConfig) -> None:
    sources = [_source(1, 500, 500, OFF), _source(2, 505, 500, OFF)]
    op = _op(offs=1)
    op = op.model_copy(
        update={"off_settings": op.off_settings.model_copy(update={"exclude_players": ["p2"]})}
    )
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    [cmd] = res.plan.commands
    assert cmd.source_id == 1  # p2 is closer but must not send an off


def test_village_can_send_off_and_nobles(world: WorldConfig) -> None:
    noble = {**OFF, Unit.SNOB: 2}
    op = _op(offs=1, nobles=2)
    res = plan_operation(op, world, [_source(1, 505, 500, noble)], [_target(op)], now=NOW)
    assert res.shortfalls == []
    off = [c for c in res.plan.commands if c.type == CommandType.ATTACK]
    nobles = [c for c in res.plan.commands if c.type == CommandType.CONQUEST]
    assert len(off) == 1
    assert len(nobles) == 2
    # escort (2 x 100 axe) is taken out of the off
    assert off[0].units[Unit.AXE] == 4800


def test_nobles_combined_from_several_players(world: WorldConfig) -> None:
    op = _op(offs=1, nobles=3)
    nobles = [_source(i, 505 + i, 500, {Unit.SNOB: 1, Unit.AXE: 200}) for i in range(1, 4)]
    off = _source(9, 495, 500, OFF)  # far away -> sent before all AGs
    res = plan_operation(op, world, [*nobles, off], [_target(op)], now=NOW)
    assert res.shortfalls == []
    ags = [c for c in res.plan.commands if c.type == CommandType.CONQUEST]
    assert sorted(c.source_id for c in ags) == [1, 2, 3]


def test_nobles_without_any_off_are_never_planned(world: WorldConfig) -> None:
    op = _op(nobles=1)
    res = plan_operation(op, world, [_source(1, 505, 500, {Unit.SNOB: 1, Unit.AXE: 200})],
                         [_target(op)], now=NOW)  # fmt: skip
    assert res.plan.commands == []
    assert any("keine Off" in w for w in res.plan.warnings)


def _wing(ctype: CommandType, send_h: int, send_m: int, units: dict[Unit, int]) -> PlannedCommand:
    arrival = datetime(2026, 11, 7, 12, 0, tzinfo=TZ)
    send = datetime(2026, 11, 7, send_h, send_m, tzinfo=TZ)
    return PlannedCommand(
        source_id=500, target_id=99, units=units, slowest_unit=Unit.RAM, type=ctype,
        arrival=arrival, send=send, travel=arrival - send, note="wing -> enemy", origin="dsu:1",
    )  # fmt: skip


def test_wing_off_covers_our_noble(world: WorldConfig) -> None:
    op = _op(nobles=1)
    wing_off = _wing(CommandType.ATTACK, 6, 0, OFF)  # sent 06:00, long before our AG
    src = _source(1, 505, 500, {Unit.SNOB: 1, Unit.AXE: 200})  # AG sent 09:05
    res = plan_operation(op, world, [src], [_target(op)], now=NOW, existing=[wing_off])
    assert [c.type for c in res.plan.commands] == [CommandType.CONQUEST]


def test_our_off_covers_wing_noble(world: WorldConfig) -> None:
    op = _op(offs=1)
    wing_ag = _wing(CommandType.CONQUEST, 10, 0, {Unit.SNOB: 1})  # wing AG sent 10:00
    near = _source(1, 508, 500, OFF)  # off sent 11:00 -> too late for same second
    far = _source(2, 500, 500, OFF)  # off sent 07:00 -> before the wing AG
    res = plan_operation(op, world, [near, far], [_target(op)], now=NOW, existing=[wing_ag])
    [off] = res.plan.commands
    assert off.source_id == 2
    assert not any("KEINE Off" in w for w in res.plan.warnings)


def test_small_offs_are_never_combined(world: WorldConfig) -> None:
    half = {Unit.AXE: 1000, Unit.LIGHT: 150, Unit.RAM: 20}  # 1700 pop: not a full off
    op = _op(offs=1)
    sources = [_source(1, 505, 500, half), _source(2, 506, 500, half)]
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    assert res.plan.commands == []


def test_old_files_with_fusion_still_load() -> None:
    op = _op(offs=1, fusion=True)  # removed option is ignored
    assert op.targets[0].offs == 1
    assert (
        Operation.model_validate(
            {**op.model_dump(mode="json"), "off_settings": {"fusion_min_pop": 500}}
        ).off_settings.min_pop
        == 3000
    )


def test_fake_respects_fake_limit(world: WorldConfig) -> None:
    sources = [_source(1, 505, 500, {Unit.RAM: 5, Unit.SPEAR: 500})]
    op = _op(fakes=1)
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    [cmd] = res.plan.commands
    # 5000 points * 1% = 50 pop: 1 ram (5) + 45 spear
    assert cmd.units == {Unit.RAM: 1, Unit.SPEAR: 45}
    assert cmd.type == CommandType.FAKE


def test_send_window_excludes_candidates(world: WorldConfig) -> None:
    op = _op(offs=1)
    op = op.model_copy(update={"send_window": SendWindow(start=time(7), end=time(23))})
    # 18 fields * 30 min = 9 h -> send at 03:00, outside 07:00-23:00
    res = plan_operation(op, world, [_source(1, 492, 500, OFF)], [_target(op)], now=NOW)
    assert res.plan.commands == []
    assert res.shortfalls == [
        "510|500: nur 0/1 volle Offs (0 Dörfer mit voller Off erreichen das Ziel im Zeitfenster)."
        " 1 weitere müssten außerhalb des Abschickfensters (07:00-23:00) losschicken"
        " - Ankunft oder Abschickfenster ändern."
    ]


def test_two_offs_need_two_villages(world: WorldConfig) -> None:
    big = {Unit.AXE: 8000, Unit.LIGHT: 3000, Unit.RAM: 300}  # ~ 21500 pop
    op = _op(offs=2)
    res = plan_operation(op, world, [_source(1, 505, 500, big)], [_target(op)], now=NOW)
    assert len(res.plan.commands) == 1
    assert res.shortfalls == [
        "510|500: nur 1/2 volle Offs (1 Dörfer mit voller Off erreichen das Ziel im Zeitfenster)."
    ]


def test_ag_never_lands_before_an_off_same_second(world: WorldConfig) -> None:
    # Off village is close (sent late), noble village far (sent early): in the same second
    # the AG would land first -> the planner must break the second.
    op = _op(offs=1, nobles=1)
    sources = [
        _source(1, 508, 500, OFF),  # 2 fields: off sent 1 h before
        _source(2, 500, 500, {Unit.SNOB: 1, Unit.AXE: 200}),  # 10 fields: AG sent ~5.8 h before
    ]
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    off = next(c for c in res.plan.commands if c.type == CommandType.ATTACK)
    ag = next(c for c in res.plan.commands if c.type == CommandType.CONQUEST)
    assert off.arrival == ag.arrival - timedelta(seconds=1)
    assert any("Sekunde gebrochen" in w for w in res.plan.warnings)


def test_same_second_when_off_is_sent_first(world: WorldConfig) -> None:
    op = _op(offs=1, nobles=1)
    sources = [
        _source(1, 500, 500, OFF),  # 10 fields: off sent 5 h before
        _source(2, 507, 500, {Unit.SNOB: 1, Unit.AXE: 200}),  # 3 fields: AG sent 1:45 before
    ]
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    off = next(c for c in res.plan.commands if c.type == CommandType.ATTACK)
    ag = next(c for c in res.plan.commands if c.type == CommandType.CONQUEST)
    assert off.arrival == ag.arrival
    assert off.send < ag.send
    assert not any("Sekunde gebrochen" in w for w in res.plan.warnings)


def test_no_second_break_allowed_drops_the_ag(world: WorldConfig) -> None:
    op = _op(offs=1, nobles=1).model_copy(update={"allow_second_break": False})
    sources = [
        _source(1, 508, 500, OFF),
        _source(2, 500, 500, {Unit.SNOB: 1, Unit.AXE: 200}),
    ]
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    # never an AG without an off before it: the AG is rather not planned
    assert not [c for c in res.plan.commands if c.type == CommandType.CONQUEST]


def test_home_guard_stays_home(world: WorldConfig) -> None:
    op = _op(fakes=1).model_copy(update={"home_guard": {Unit.SPEAR: 50, Unit.SPY: 51}})
    # 500 spear - 50 guard = 450 available; fake needs 45 spear + 1 ram
    res = plan_operation(op, world, [_source(1, 505, 500, {Unit.RAM: 5, Unit.SPEAR: 95})],
                         [_target(op)], now=NOW)  # fmt: skip
    [cmd] = res.plan.commands
    assert cmd.units == {Unit.RAM: 1, Unit.SPEAR: 45}
    res2 = plan_operation(op, world, [_source(1, 505, 500, {Unit.RAM: 5, Unit.SPEAR: 94})],
                          [_target(op)], now=NOW)  # fmt: skip
    assert res2.plan.commands == []  # only 44 spear left after the guard


DEFF = {Unit.SPEAR: 3000, Unit.SWORD: 3000}


def test_support_lands_at_fixed_time_after_last_ag(world: WorldConfig) -> None:
    sources = [_source(1, 505, 500, {**OFF, Unit.SNOB: 1}), _source(2, 507, 500, DEFF)]
    op = _op(offs=1, nobles=1, support={"min_pop": 1000, "arrival": "2026-11-07 12:00:01"})
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    [sup] = [c for c in res.plan.commands if c.type == CommandType.SUPPORT]
    assert sup.arrival == datetime(2026, 11, 7, 12, 0, 1, tzinfo=TZ)


def test_support_fixed_before_last_ag_is_not_planned(world: WorldConfig) -> None:
    sources = [_source(1, 505, 500, {**OFF, Unit.SNOB: 1}), _source(2, 507, 500, DEFF)]
    op = _op(offs=1, nobles=1, support={"min_pop": 1000, "arrival": "2026-11-07 11:59:59"})
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    assert not [c for c in res.plan.commands if c.type == CommandType.SUPPORT]
    assert any("vor dem letzten AG" in w for w in res.plan.warnings)


def test_fake_ag_never_lands_before_the_off(world: WorldConfig) -> None:
    # far village: fake AG sent early; close village: off sent late -> same second not allowed
    sources = [_source(1, 490, 500, {**OFF, Unit.SNOB: 1}), _source(2, 507, 500, OFF)]
    op = _op(offs=1, fake_nobles=1)
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    [off] = [c for c in res.plan.commands if c.type == CommandType.ATTACK]
    for fag in (c for c in res.plan.commands if c.slowest_unit == Unit.SNOB):
        assert off.arrival < fag.arrival or off.send <= fag.send - timedelta(seconds=2)


def test_support_same_second_after_last_ag_else_plus_one(world: WorldConfig) -> None:
    sources = [
        _source(1, 505, 500, {**OFF, Unit.SNOB: 4}),  # 4 AGs, sent 175 min before
        _source(2, 507, 500, DEFF),  # close: sent after the AGs -> same second
        _source(3, 480, 500, DEFF),  # far: would be sent before the AGs -> +1 s
    ]
    op = _op(offs=1, nobles=4, support={"min_pop": 100_000})
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    ags = [c for c in res.plan.commands if c.type == CommandType.CONQUEST]
    assert len(ags) == 4
    last = max(ags, key=lambda c: (c.arrival, c.send))
    sups = {c.source_id: c for c in res.plan.commands if c.type == CommandType.SUPPORT}
    assert sups[2].arrival == last.arrival
    assert sups[2].send >= last.send + timedelta(seconds=2)
    assert sups[3].arrival == last.arrival + timedelta(seconds=1)
    assert any("1 s nach den AGs" in w for w in res.plan.warnings)


def test_support_few_villages_prefers_same_second(world: WorldConfig) -> None:
    sources = [
        _source(1, 505, 500, {**OFF, Unit.SNOB: 1}),
        _source(2, 507, 500, {Unit.SPEAR: 600, Unit.SWORD: 600}),  # small, same second
        _source(3, 480, 500, DEFF),  # big, only +1 s
    ]
    op = _op(offs=1, nobles=1, support={"min_pop": 1000, "few_villages": True})
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    sups = [c for c in res.plan.commands if c.type == CommandType.SUPPORT]
    assert [c.source_id for c in sups] == [2]


def test_support_few_villages_takes_biggest_first(world: WorldConfig) -> None:
    small = {Unit.SPEAR: 600, Unit.SWORD: 600}
    sources = [
        _source(1, 505, 500, {**OFF, Unit.SNOB: 1}),
        _source(2, 508, 500, small),
        _source(3, 509, 500, small),
        _source(4, 503, 500, DEFF),  # big, also in the AG second
    ]
    op = _op(offs=1, nobles=1, support={"min_pop": 2000, "few_villages": True})
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    sups = [c for c in res.plan.commands if c.type == CommandType.SUPPORT]
    assert [c.source_id for c in sups] == [4]


def test_support_troops_not_planned_twice(world: WorldConfig) -> None:
    op = Operation.model_validate(
        {
            "name": "t",
            "world": "de260",
            "arrival": "2026-11-07 12:00:00",
            "send_window": {"start": "00:00", "end": "23:59:59"},
            "targets": [
                {"coord": "510|500", "offs": 1, "nobles": 1, "support": {"min_pop": 1000}},
                {"coord": "510|502", "offs": 1, "nobles": 1, "support": {"min_pop": 1000}},
            ],
        }
    )
    noble = {**OFF, Unit.SNOB: 1}
    sources = [_source(1, 505, 500, noble), _source(2, 505, 502, noble), _source(3, 507, 501, DEFF)]
    targets = [
        Target(op.targets[0], _village(98, 510, 500, player=2), "enemy"),
        Target(op.targets[1], _village(99, 510, 502, player=2), "enemy"),
    ]
    res = plan_operation(op, world, sources, targets, now=NOW)
    sups = [c for c in res.plan.commands if c.source_id == 3]
    assert sum(c.units.get(Unit.SPEAR, 0) for c in sups) <= DEFF[Unit.SPEAR]


def test_tab_off_lands_between_the_ags(world: WorldConfig) -> None:
    ag = {Unit.SNOB: 1, Unit.AXE: 100}
    sources = [
        _source(1, 500, 500, OFF),  # main off, sent long before the AGs
        _source(2, 508, 500, ag),  # AG sent 70 min before arrival
        _source(3, 504, 500, ag),  # AG sent 210 min before arrival
        _source(4, 506, 500, {Unit.AXE: 2000, Unit.RAM: 1}),  # ram 4 fields: 120 min -> between
        _source(5, 509, 500, {Unit.AXE: 3000, Unit.RAM: 1}),  # 30 min: after both AGs
    ]
    op = _op(offs=1, nobles=2, tab_offs=1)
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    assert res.shortfalls == []
    [tab] = [c for c in res.plan.commands if c.role == "tab"]
    assert tab.source_id == 4
    assert tab.type == CommandType.ATTACK
    ag_sends = sorted(c.send for c in res.plan.commands if c.type == CommandType.CONQUEST)
    assert ag_sends[0] < tab.send < ag_sends[-1]
    assert tab.arrival == datetime(2026, 11, 7, 12, 0, tzinfo=TZ)


def test_tab_off_impossible_without_ag_on_both_sides(world: WorldConfig) -> None:
    ag = {Unit.SNOB: 1, Unit.AXE: 100}
    sources = [
        _source(1, 500, 500, OFF),
        _source(2, 508, 500, ag),
        _source(5, 509, 500, {Unit.AXE: 3000, Unit.RAM: 1}),  # only after the AG
    ]
    op = _op(offs=1, nobles=1, tab_offs=1)
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    assert not any(c.role == "tab" for c in res.plan.commands)
    assert any("Tab-Offs" in s for s in res.shortfalls)


def test_nobles_from_restricts_who_nobles(world: WorldConfig) -> None:
    ag = {Unit.SNOB: 1, Unit.AXE: 100}
    sources = [_source(1, 500, 500, OFF), _source(2, 508, 500, ag), _source(3, 504, 500, ag)]
    op = _op(offs=1, nobles=1, nobles_from=["P3"])
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    [noble] = [c for c in res.plan.commands if c.type == CommandType.CONQUEST]
    assert noble.source_id == 3  # p2 is closer, but p3 should noble
    op = _op(offs=1, nobles=1, nobles_from=["508|500"])
    res = plan_operation(op, world, sources, [_target(op)], now=NOW)
    [noble] = [c for c in res.plan.commands if c.type == CommandType.CONQUEST]
    assert noble.source_id == 2


def test_shortfall_names_the_send_window(world: WorldConfig) -> None:
    op = _op(offs=1).model_copy(update={"send_window": SendWindow(start=time(7), end=time(23))})
    # 5 fields, ram 30 min/field: arrival 12:00 -> send 09:30 is fine ...
    res = plan_operation(op, world, [_source(1, 505, 500, OFF)], [_target(op)], now=NOW)
    assert res.shortfalls == []
    # ... arrival 08:00 -> send 05:30, outside 07:00-23:00
    early = op.model_copy(update={"arrival": datetime(2026, 11, 7, 8, 0, tzinfo=TZ)})
    res = plan_operation(early, world, [_source(1, 505, 500, OFF)], [_target(early)], now=NOW)
    assert any("außerhalb des Abschickfensters (07:00-23:00)" in s for s in res.shortfalls)
