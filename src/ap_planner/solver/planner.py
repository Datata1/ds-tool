"""Assign source villages to targets with CP-SAT, using per-village troop budgets.

Every village has a budget per unit. The solver decides freely what each village does:
send its off (once per operation), contribute noblemen (+escort), send fakes and fake
nobles, all at the same time as long as the budget holds. If the village sends an off,
the off is *everything that remains* of the off units after escorts and fakes, and must
still be at least ``min_pop`` (or ``fusion_min_pop`` on fusion targets).

Noblemen for one target may come from many villages and players. On worlds without ms
control all nobles land in the same second.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model

from ap_planner.domain import travel
from ap_planner.domain.night import in_night_bonus
from ap_planner.models.map import Village
from ap_planner.models.operation import Operation, SupportOrder, TargetOrder
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.troops import VillageTroops
from ap_planner.models.world import Unit, WorldConfig

# Objective weights: missing things are much worse than long runtimes.
PENALTY_NOBLE = 10_000_000
PENALTY_FAKE_NOBLE = 1_000_000
PENALTY_OFF_POP = 1_000  # per missing off population (3000 pop = 3M)
PENALTY_FAKE = 100_000
PENALTY_SECOND_BREAK = 50_000  # same second is preferred, breaking is the fallback
KINDS = ("off", "noble", "fake", "fake_noble")


@dataclass(frozen=True)
class Source:
    """A village that may attack, with its troops and owner."""

    village: Village
    player: str
    troops: VillageTroops
    captured_at: datetime


@dataclass(frozen=True)
class Target:
    order: TargetOrder
    village: Village
    owner: str


@dataclass
class PlanResult:
    plan: Plan
    shortfalls: list[str] = field(default_factory=list)


@dataclass
class _Ctx:
    """Everything the model-building steps share."""

    op: Operation
    world: WorldConfig
    sources: list[Source]
    targets: list[Target]
    tz: ZoneInfo
    now: datetime
    model: cp_model.CpModel = field(default_factory=cp_model.CpModel)
    # (kind, source_id, target_id) -> decision variable (bool or int count)
    vars: dict[tuple[str, int, int], cp_model.IntVar] = field(default_factory=dict)
    # (kind, source_id, target_id) -> (arrival, travel seconds, slowest unit)
    timing: dict[tuple[str, int, int], tuple[datetime, int, Unit]] = field(default_factory=dict)
    # off population contributed (source_id, target_id) -> var
    off_pop: dict[tuple[int, int], cp_model.IntVar] = field(default_factory=dict)
    fake_comp: dict[int, dict[Unit, int]] = field(default_factory=dict)
    fake_noble_comp: dict[int, dict[Unit, int]] = field(default_factory=dict)
    objective: list[cp_model.LinearExprT] = field(default_factory=list)
    shortfalls: list[tuple[str, Target, cp_model.IntVar, int]] = field(default_factory=list)
    # target_id -> bool var: offs land 1 s before the AGs
    second_break: dict[int, cp_model.IntVar] = field(default_factory=dict)
    # target_id -> commands already in DS Ultimate plans (wing), fixed
    existing: dict[int, list[PlannedCommand]] = field(default_factory=dict)
    uncovered_fixed_ags: list[tuple[Target, PlannedCommand, cp_model.IntVar]] = field(
        default_factory=list
    )
    notes: list[str] = field(default_factory=list)


def _pop(world: WorldConfig, units: dict[Unit, int]) -> int:
    return sum(world.units[u].pop * n for u, n in units.items() if u in world.units)


def _fill_to_fake_limit(
    world: WorldConfig, src: Source, base: dict[Unit, int], filler: list[Unit]
) -> dict[Unit, int] | None:
    """Add filler units to ``base`` until the world's fake limit is met (None if impossible)."""
    units = src.troops.units
    comp = dict(base)
    need = math.ceil(src.village.points * world.fake_limit_pct / 100) - _pop(world, comp)
    for u in filler:
        if need <= 0:
            break
        if u not in world.units:
            continue
        pop_u = world.units[u].pop
        take = min(units.get(u, 0) - comp.get(u, 0), math.ceil(need / pop_u))
        if take > 0:
            comp[u] = comp.get(u, 0) + take
            need -= take * pop_u
    return comp if need <= 0 else None


def _avail(src: Source, unit: Unit) -> int:
    return src.troops.units.get(unit, 0)


def _off_units(ctx: _Ctx, src: Source) -> dict[Unit, int]:
    return {u: _avail(src, u) for u in ctx.op.off_settings.units if _avail(src, u) > 0}


# --- step 1: warnings about the input -------------------------------------------


def _input_warnings(ctx: _Ctx, arrivals: dict[int, datetime]) -> list[str]:
    warnings: list[str] = []
    max_age = timedelta(hours=ctx.op.max_troop_age_hours)
    for s in ctx.sources:
        age = ctx.now - s.captured_at
        if age > max_age:
            warnings.append(
                f"Truppen von {s.player} {s.village.coord} sind "
                f"{age.days}d {age.seconds // 3600}h alt."
            )
        if s.troops.incoming > 0:
            warnings.append(
                f"{s.player} {s.village.coord} hat {s.troops.incoming} eingehende Angriffe."
            )
    players = {s.player for s in ctx.sources}
    for t in ctx.targets:
        arrival = arrivals[t.village.id]
        if in_night_bonus(ctx.world.night, arrival, str(ctx.tz)):
            warnings.append(
                f"Ankunft {arrival:%d.%m. %H:%M:%S} auf {t.village.coord} liegt im Nachtbonus!"
            )
        if t.owner in players:
            warnings.append(f"Ziel {t.village.coord} gehört einem eigenen Spieler ({t.owner}).")
    return warnings


# --- step 2: candidates (who can reach what in time) ------------------------------


def _add_candidates(ctx: _Ctx, arrivals: dict[int, datetime]) -> None:
    op, world, m = ctx.op, ctx.world, ctx.model
    escort = op.noble_settings.escort

    def reachable(kind: str, s: Source, t: Target, unit: Unit, lead_s: int = 0) -> bool:
        arrival = arrivals[t.village.id] - timedelta(seconds=lead_s)
        dist = travel.distance(s.village.coord, t.village.coord)
        secs = travel.travel_seconds(dist, world.unit_speed_min(unit))
        send = arrival - timedelta(seconds=secs)
        if send <= ctx.now or not op.send_window.contains(send.astimezone(ctx.tz).time()):
            return False
        if unit == Unit.SNOB and dist > world.snob_max_dist:
            return False
        ctx.timing[kind, s.village.id, t.village.id] = (arrival, secs, unit)
        return True

    for s in ctx.sources:
        sid = s.village.id
        off_units = _off_units(ctx, s)
        off_total = _pop(world, off_units)
        snobs = _avail(s, Unit.SNOB)
        fake = _fill_to_fake_limit(world, s, {op.fake_settings.unit: 1}, op.fake_settings.filler)
        if _avail(s, op.fake_settings.unit) < 1:
            fake = None
        fake_noble = _fill_to_fake_limit(
            world, s, {Unit.SNOB: 1, **escort}, op.fake_settings.filler
        )
        if fake is not None:
            ctx.fake_comp[sid] = fake
        if fake_noble is not None:
            ctx.fake_noble_comp[sid] = fake_noble
        for t in ctx.targets:
            o, tid = t.order, t.village.id
            part_min = op.off_settings.fusion_min_pop if o.fusion else op.off_settings.min_pop
            if (
                o.offs
                and off_total >= part_min
                and reachable("off", s, t, travel.slowest_unit(world, off_units))
            ):
                ctx.vars["off", sid, tid] = m.new_bool_var(f"off_{sid}_{tid}")
                ctx.off_pop[sid, tid] = m.new_int_var(0, off_total, f"offpop_{sid}_{tid}")
            if o.nobles and snobs and reachable("noble", s, t, Unit.SNOB):
                ctx.vars["noble", sid, tid] = m.new_int_var(
                    0, min(snobs, o.nobles), f"nob_{sid}_{tid}"
                )
            if o.fakes and fake and reachable("fake", s, t, travel.slowest_unit(world, fake)):
                ctx.vars["fake", sid, tid] = m.new_bool_var(f"fk_{sid}_{tid}")
            if o.fake_nobles and snobs and fake_noble and reachable("fake_noble", s, t, Unit.SNOB):
                ctx.vars["fake_noble", sid, tid] = m.new_int_var(
                    0, min(snobs, o.fake_nobles), f"fnob_{sid}_{tid}"
                )


# --- step 3: troop budgets per village --------------------------------------------


def _vars_of(ctx: _Ctx, kind: str, sid: int) -> list[cp_model.IntVar]:
    return [v for (k, a, _), v in ctx.vars.items() if k == kind and a == sid]


def _add_budgets(ctx: _Ctx) -> None:
    op, world, m = ctx.op, ctx.world, ctx.model
    escort = op.noble_settings.escort
    off_set = set(op.off_settings.units)
    for s in ctx.sources:
        sid = s.village.id
        nobles = sum(_vars_of(ctx, "noble", sid))
        fakes = sum(_vars_of(ctx, "fake", sid))
        fake_nobles = sum(_vars_of(ctx, "fake_noble", sid))
        offs = _vars_of(ctx, "off", sid)
        m.add(sum(offs) <= 1)  # a village sends its off at most once per operation
        m.add(nobles + fake_nobles <= _avail(s, Unit.SNOB))
        m.add(fakes + fake_nobles <= op.fake_settings.max_per_village)

        # Units consumed by escorts and fakes, per unit type.
        fake_c = ctx.fake_comp.get(sid, {})
        fnob_c = ctx.fake_noble_comp.get(sid, {})
        used: dict[Unit, cp_model.LinearExprT] = {}
        for u in set(escort) | set(fake_c) | set(fnob_c):
            if u == Unit.SNOB:
                continue
            expr = escort.get(u, 0) * nobles + fake_c.get(u, 0) * fakes
            expr += fnob_c.get(u, 0) * fake_nobles
            m.add(expr <= _avail(s, u))
            used[u] = expr

        # The off is what remains of the off units; contributed pop <= remaining pop.
        off_total = _pop(world, _off_units(ctx, s))
        used_off_pop = sum(world.units[u].pop * e for u, e in used.items() if u in off_set)
        for t in ctx.targets:
            key = ("off", sid, t.village.id)
            if key not in ctx.vars:
                continue
            o, pop = ctx.vars[key], ctx.off_pop[sid, t.village.id]
            part_min = op.off_settings.fusion_min_pop if t.order.fusion else op.off_settings.min_pop
            m.add(pop <= off_total * o)
            m.add(pop >= part_min * o)
            m.add(pop <= off_total - used_off_pop)


# --- step 4: AG ordering rule ------------------------------------------------------
#
# No ms on the world: commands landing in the same second arrive in SEND order.
# Hard rule: an AG never lands without an off before it. An off is "before" an AG if
# it lands in an earlier second, or in the same second and was sent at least
# ``off_send_gap_s`` earlier. Existing commands (wing plans) count on both sides:
# a wing off can cover our AGs, and wing AGs need an off before them (ours if needed).
# Fallback: our offs land 1 s earlier ("Sekunde brechen").


Key = tuple[str, int, int]
Times = tuple[datetime, datetime]


def _off_before(
    off: tuple[datetime, datetime], ag: tuple[datetime, datetime], gap: timedelta
) -> bool:
    """off/ag = (arrival, send)."""
    return off[0] < ag[0] or (off[0] == ag[0] and off[1] <= ag[1] - gap)


def _times(ctx: _Ctx, key: tuple[str, int, int]) -> tuple[datetime, datetime]:
    arrival, secs, _ = ctx.timing[key]
    return arrival, arrival - timedelta(seconds=secs)


def _add_noble_ordering(ctx: _Ctx) -> None:
    m, op = ctx.model, ctx.op
    gap = timedelta(seconds=op.off_send_gap_s)
    for t in ctx.targets:
        tid = t.village.id
        # Fake AGs carry a real nobleman: they also need an off landing before them.
        nobles = {
            k: v for k, v in ctx.vars.items() if k[0] in ("noble", "fake_noble") and k[2] == tid
        }
        offs = {k: v for k, v in ctx.vars.items() if k[0] == "off" and k[2] == tid}
        fixed = ctx.existing.get(tid, [])
        fixed_offs = [
            (c.arrival, c.send)
            for c in fixed
            if c.type in (CommandType.ATTACK, CommandType.WALLBREAKER)
        ]
        fixed_ags = [
            c for c in fixed if c.type == CommandType.CONQUEST or c.slowest_unit == Unit.SNOB
        ]
        if not nobles and not fixed_ags:
            continue

        brk: cp_model.IntVar | None = None
        if offs:
            brk = m.new_bool_var(f"break_{tid}")
            if not op.allow_second_break:
                m.add(brk == 0)
            ctx.second_break[tid] = brk
            ctx.objective.append(PENALTY_SECOND_BREAK * brk)

        common = {"offs": offs, "fixed_offs": fixed_offs, "brk": brk, "gap": gap}
        _order_own_nobles(ctx, t, nobles=nobles, **common)
        _order_fixed_nobles(ctx, t, fixed_ags=fixed_ags, **common)


def _order_own_nobles(
    ctx: _Ctx,
    t: Target,
    *,
    nobles: dict[Key, cp_model.IntVar],
    offs: dict[Key, cp_model.IntVar],
    fixed_offs: list[Times],
    brk: cp_model.IntVar | None,
    gap: timedelta,
) -> None:
    """Our AGs: need a wing off before them, or our offs sent first (or a broken second)."""
    m, tid = ctx.model, t.village.id
    for nkey, nvar in nobles.items():
        ag = _times(ctx, nkey)
        wing_covers = any(_off_before(fo, ag, gap) for fo in fixed_offs)
        used = m.new_bool_var(f"use_{nkey[0]}_{nkey[1]}_{tid}")
        m.add(nvar >= used)
        m.add(nvar <= (t.order.nobles if nkey[0] == "noble" else t.order.fake_nobles) * used)
        if not offs or brk is None:
            if not wing_covers:
                m.add(used == 0)  # no off at all -> never send this AG
            continue
        if not wing_covers:
            m.add(sum(offs.values()) >= used)
        # Our own offs on this target always land before our AGs (they are meant to clear).
        for okey, ovar in offs.items():
            if not _off_before(_times(ctx, okey), ag, gap):
                # this off would land after the AG -> only allowed if the second is broken
                m.add_bool_or([ovar.Not(), used.Not(), brk])


def _order_fixed_nobles(
    ctx: _Ctx,
    t: Target,
    *,
    fixed_ags: list[PlannedCommand],
    offs: dict[Key, cp_model.IntVar],
    fixed_offs: list[Times],
    brk: cp_model.IntVar | None,
    gap: timedelta,
) -> None:
    """Wing AGs without a wing off before them must be covered by one of our offs."""
    m, tid, one = ctx.model, t.village.id, timedelta(seconds=1)
    for i, f in enumerate(fixed_ags):
        ag = (f.arrival, f.send)
        if any(_off_before(fo, ag, gap) for fo in fixed_offs):
            continue
        cover: list[cp_model.IntVar] = []
        for okey, ovar in offs.items():
            arr, snd = _times(ctx, okey)
            q0 = _off_before((arr, snd), ag, gap)  # same second as planned
            q1 = _off_before((arr - one, snd - one), ag, gap)  # second broken
            if not (q0 or q1) or brk is None:
                continue
            c = m.new_bool_var(f"cover_{tid}_{i}_{okey[1]}")
            m.add(c <= ovar)
            if q0 and not q1:
                m.add(c <= 1 - brk)
            elif q1 and not q0:
                m.add(c <= brk)
            cover.append(c)
        miss = m.new_bool_var(f"wingag_uncovered_{tid}_{i}")
        m.add(sum(cover) + miss >= 1)
        ctx.objective.append(PENALTY_NOBLE * miss)
        ctx.uncovered_fixed_ags.append((t, f, miss))


# --- step 5: demands per target + objective -------------------------------------------


def _add_required_offs(ctx: _Ctx) -> None:
    """``off_from``: these villages must send their off to the target."""
    by_coord = {s.village.coord: s for s in ctx.sources}
    for t in ctx.targets:
        for coord in t.order.off_from:
            src = by_coord.get(coord)
            key = ("off", src.village.id, t.village.id) if src else None
            if key is None or key not in ctx.vars:
                why = (
                    "keine Truppen importiert"
                    if src is None
                    else "Off zu klein / nicht im Zeitfenster"
                )
                ctx.notes.append(
                    f"{t.village.coord}: Pflicht-Off aus {coord} nicht möglich ({why})."
                )
                continue
            ctx.model.add(ctx.vars[key] == 1)


def _add_demands(ctx: _Ctx) -> None:
    m, min_pop = ctx.model, ctx.op.off_settings.min_pop
    for t in ctx.targets:
        o, tid = t.order, t.village.id
        if o.offs:
            pops = [p for (_, b), p in ctx.off_pop.items() if b == tid]
            count = [v for (k, _, b), v in ctx.vars.items() if k == "off" and b == tid]
            if o.fusion:
                # Fusion: off strength counts, parts may come from several villages.
                need = o.offs * min_pop
                short = m.new_int_var(0, need, f"short_off_{tid}")
                m.add(short >= need - sum(pops))
                m.add(sum(count) <= o.offs * 4)
                ctx.objective.append(PENALTY_OFF_POP * short)
                ctx.shortfalls.append(("off", t, short, need))
            else:
                # Normal: each off is one village with a full off.
                short = m.new_int_var(0, o.offs, f"short_off_{tid}")
                m.add(sum(count) <= o.offs)
                m.add(short >= o.offs - sum(count))
                ctx.objective.append(PENALTY_OFF_POP * min_pop * short)
                ctx.shortfalls.append(("off", t, short, o.offs))
        for kind, wanted, penalty in (
            ("noble", o.nobles, PENALTY_NOBLE),
            ("fake", o.fakes, PENALTY_FAKE),
            ("fake_noble", o.fake_nobles, PENALTY_FAKE_NOBLE),
        ):
            if not wanted:
                continue
            got = [v for (k, _, b), v in ctx.vars.items() if k == kind and b == tid]
            short = m.new_int_var(0, wanted, f"short_{kind}_{tid}")
            m.add(sum(got) <= wanted)
            m.add(short >= wanted - sum(got))
            ctx.objective.append(penalty * short)
            ctx.shortfalls.append((kind, t, short, wanted))

    # Secondary: short runtimes for real attacks (in minutes); fakes barely matter.
    for key, (_, secs, _) in ctx.timing.items():
        if key in ctx.vars:
            weight = 10 if key[0] in ("off", "noble") else 1
            ctx.objective.append(weight * (secs // 60) * ctx.vars[key])
    m.minimize(sum(ctx.objective))


# --- step 6: read the solution back --------------------------------------------------


def _commands(ctx: _Ctx, solver: cp_model.CpSolver) -> list[PlannedCommand]:
    op = ctx.op
    by_id = {s.village.id: s for s in ctx.sources}
    tgt = {t.village.id: t for t in ctx.targets}
    escort = {u: n for u, n in op.noble_settings.escort.items() if n > 0}
    commands: list[PlannedCommand] = []
    per_source: dict[int, dict[str, int]] = {}

    def add(kind: str, sid: int, tid: int, units: dict[Unit, int], ctype: CommandType) -> None:
        arrival, secs, unit = ctx.timing[kind, sid, tid]
        brk = ctx.second_break.get(tid)
        if kind == "off" and brk is not None and solver.value(brk):
            arrival -= timedelta(seconds=1)
        commands.append(
            PlannedCommand(
                source_id=sid,
                target_id=tid,
                source_player_id=by_id[sid].village.player_id,
                units=units,
                slowest_unit=unit,
                type=ctype,
                arrival=arrival,
                send=arrival - timedelta(seconds=secs),
                travel=timedelta(seconds=secs),
                note=f"{by_id[sid].player} -> {tgt[tid].owner}",
            )
        )

    for (kind, sid, tid), var in ctx.vars.items():
        n = solver.value(var)
        if not n:
            continue
        per_source.setdefault(sid, dict.fromkeys(KINDS, 0))[kind] += n
        if kind == "noble":
            for _ in range(n):
                add(kind, sid, tid, {Unit.SNOB: 1, **escort}, CommandType.CONQUEST)
        elif kind == "fake_noble":
            for _ in range(n):
                add(kind, sid, tid, ctx.fake_noble_comp[sid], CommandType.FAKE)
        elif kind == "fake":
            add(kind, sid, tid, ctx.fake_comp[sid], CommandType.FAKE)

    # Offs last: they take what remains after escorts and fakes.
    for (kind, sid, tid), var in ctx.vars.items():
        if kind != "off" or not solver.value(var):
            continue
        used = per_source.get(sid, dict.fromkeys(KINDS, 0))
        fake_c = ctx.fake_comp.get(sid, {})
        fnob_c = ctx.fake_noble_comp.get(sid, {})
        remaining: dict[Unit, int] = {}
        for u, n in _off_units(ctx, by_id[sid]).items():
            left = n - escort.get(u, 0) * used["noble"]
            left -= fake_c.get(u, 0) * used["fake"] + fnob_c.get(u, 0) * used["fake_noble"]
            if left > 0:
                remaining[u] = left
        add("off", sid, tid, remaining, CommandType.ATTACK)

    commands.sort(key=lambda c: (c.send, c.source_id))
    return commands


def _explain_shortfalls(ctx: _Ctx, solver: cp_model.CpSolver) -> list[str]:
    labels = {"noble": "AGs", "fake": "Fakes", "fake_noble": "Fake-AGs"}
    out: list[str] = []
    for kind, t, short, wanted in ctx.shortfalls:
        missing = solver.value(short)
        if not missing:
            continue
        cands = {a for (k, a, b) in ctx.vars if k == kind and b == t.village.id}
        if kind == "off" and t.order.fusion:
            min_pop = ctx.op.off_settings.min_pop
            got = (wanted - missing) / min_pop
            out.append(
                f"{t.village.coord}: nur {got:.1f}/{wanted // min_pop} Offs (Fusion) "
                f"({len(cands)} Off-Dörfer erreichen das Ziel im Zeitfenster)."
            )
        elif kind == "off":
            out.append(
                f"{t.village.coord}: nur {wanted - missing}/{wanted} volle Offs "
                f"({len(cands)} Dörfer mit voller Off erreichen das Ziel im Zeitfenster)."
            )
        else:
            out.append(
                f"{t.village.coord}: {wanted - missing}/{wanted} {labels[kind]} geplant "
                f"({len(cands)} passende Dörfer in Reichweite und Zeitfenster)."
            )
    return out


# --- reserved troops (attacks we keep from existing plans) -----------------------------


def _estimate_units(
    world: WorldConfig, op: Operation, src: Source, cmd: PlannedCommand
) -> dict[Unit, int]:
    """Units a kept command uses. Wing/DSU plans often have no unit counts -> estimate."""
    if cmd.units:
        units = dict(cmd.units)
        if cmd.type == CommandType.CONQUEST or cmd.slowest_unit == Unit.SNOB:
            units[Unit.SNOB] = max(1, units.get(Unit.SNOB, 0))  # an AG command has an AG
        return units
    if cmd.type == CommandType.FAKE:
        if cmd.slowest_unit == Unit.SNOB:
            return {Unit.SNOB: 1, **op.noble_settings.escort}
        comp = _fill_to_fake_limit(world, src, {op.fake_settings.unit: 1}, op.fake_settings.filler)
        return comp or {op.fake_settings.unit: 1}
    if cmd.type == CommandType.CONQUEST:
        return {Unit.SNOB: 1, **op.noble_settings.escort}
    if cmd.type in (CommandType.ATTACK, CommandType.WALLBREAKER):
        return {u: src.troops.units.get(u, 0) for u in op.off_settings.units}
    return {}


def apply_home_guard(op: Operation, sources: list[Source]) -> list[Source]:
    """Fake protection: these units always stay home and are never planned."""
    if not op.home_guard:
        return sources
    out: list[Source] = []
    for s in sources:
        units = {u: max(0, n - op.home_guard.get(u, 0)) for u, n in s.troops.units.items()}
        out.append(
            Source(s.village, s.player, s.troops.model_copy(update={"units": units}), s.captured_at)
        )
    return out


def reserve_troops(
    world: WorldConfig, op: Operation, sources: list[Source], kept: list[PlannedCommand]
) -> tuple[list[Source], list[str]]:
    """Subtract troops of kept own commands from the sources' budgets."""
    by_id = {s.village.id: s for s in sources}
    used: dict[int, dict[Unit, int]] = {}
    notes: list[str] = []
    for c in kept:
        src = by_id.get(c.source_id)
        if src is None:
            continue
        for u, n in _estimate_units(world, op, src, c).items():
            used.setdefault(c.source_id, {}).setdefault(u, 0)
            used[c.source_id][u] += n
    out: list[Source] = []
    for s in sources:
        if s.village.id not in used:
            out.append(s)
            continue
        units = {u: max(0, n - used[s.village.id].get(u, 0)) for u, n in s.troops.units.items()}
        short = [u.value for u, n in used[s.village.id].items() if n > s.troops.units.get(u, 0)]
        if short:
            notes.append(
                f"{s.player} {s.village.coord}: behaltene Angriffe brauchen mehr {', '.join(short)}"
                " als vorhanden."
            )
        out.append(
            Source(s.village, s.player, s.troops.model_copy(update={"units": units}), s.captured_at)
        )
    return out, notes


# --- support (flex deff) after the last AG ------------------------------------------


SupportOption = tuple[datetime, int, Source, dict[Unit, int], Unit]


def _support_arrivals(
    order: SupportOrder, last: PlannedCommand, tz: ZoneInfo
) -> tuple[datetime, ...]:
    """Landing times to try: a fixed one (if not before the last AG) or right after it."""
    if order.arrival is None:
        return (last.arrival, last.arrival + timedelta(seconds=1))
    fixed = order.arrival
    fixed = fixed.replace(tzinfo=tz) if fixed.tzinfo is None else fixed.astimezone(tz)
    return (fixed,) if fixed >= last.arrival else ()


def _support_options(
    ctx: _Ctx,
    t: Target,
    *,
    order: SupportOrder,
    last: PlannedCommand,
    used: dict[int, dict[Unit, int]],
    gap: timedelta,
) -> list[SupportOption]:
    """Possible support commands, earliest landing first (never before the last AG)."""
    op, world = ctx.op, ctx.world
    options: list[SupportOption] = []
    for s in ctx.sources:
        left = {
            u: s.troops.units.get(u, 0) - used.get(s.village.id, {}).get(u, 0) for u in order.units
        }
        avail = {
            u: int(n * (1 - order.keep_home_share))
            for u, n in left.items()
            if n > 0 and u in world.units
        }
        avail = {u: n for u, n in avail.items() if n > 0}
        if not avail:
            continue
        unit = travel.slowest_unit(world, avail)
        secs = travel.travel_seconds(
            travel.distance(s.village.coord, t.village.coord), world.unit_speed_min(unit)
        )
        for arrival in _support_arrivals(order, last, ctx.tz):
            send = arrival - timedelta(seconds=secs)
            if arrival == last.arrival and send < last.send + gap:
                continue  # would land before the last AG
            if send <= ctx.now or not op.send_window.contains(send.astimezone(ctx.tz).time()):
                continue
            options.append((arrival, secs, s, avail, unit))
            break
    return sorted(options, key=lambda o: (o[0], o[1]))


def _plan_supports(
    ctx: _Ctx, commands: list[PlannedCommand], warnings: list[str]
) -> list[PlannedCommand]:
    """Supports land after the last AG on the target (same second sent later, or +1 s)."""
    world = ctx.world
    gap = timedelta(seconds=ctx.op.off_send_gap_s)
    used: dict[int, dict[Unit, int]] = {}
    for c in commands:
        for u, n in c.units.items():
            used.setdefault(c.source_id, {}).setdefault(u, 0)
            used[c.source_id][u] += n
    out: list[PlannedCommand] = []
    for t in ctx.targets:
        order = t.order.support
        if order is None:
            continue
        tid = t.village.id
        ags = [
            c
            for c in [*commands, *ctx.existing.get(tid, [])]
            if c.target_id == tid and c.type == CommandType.CONQUEST
        ]
        if not ags:
            warnings.append(f"{t.village.coord}: Unterstützung geplant, aber kein AG auf dem Ziel.")
            continue
        last = max(ags, key=lambda c: (c.arrival, c.send))
        if not _support_arrivals(order, last, ctx.tz):
            warnings.append(
                f"{t.village.coord}: Unterstützung soll vor dem letzten AG landen - nicht geplant."
            )
            continue
        options = _support_options(ctx, t, order=order, last=last, used=used, gap=gap)
        got = 0
        for arrival, secs, s, avail, unit in options:
            if got >= order.min_pop:
                break
            got += _pop(world, avail)
            out.append(
                PlannedCommand(
                    source_id=s.village.id,
                    target_id=tid,
                    source_player_id=s.village.player_id,
                    units=avail,
                    slowest_unit=unit,
                    type=CommandType.SUPPORT,
                    arrival=arrival,
                    send=arrival - timedelta(seconds=secs),
                    travel=timedelta(seconds=secs),
                    note=f"{s.player} -> {t.owner}",
                )
            )
        if got < order.min_pop:
            warnings.append(
                f"{t.village.coord}: nur {got}/{order.min_pop} Deff-Plätze Unterstützung möglich."
            )
    return out


def plan_operation(
    op: Operation,
    world: WorldConfig,
    sources: list[Source],
    targets: list[Target],
    *,
    tz_name: str = "Europe/Berlin",
    now: datetime | None = None,
    existing: list[PlannedCommand] | None = None,
    time_limit_s: float = 30.0,
) -> PlanResult:
    tz = ZoneInfo(tz_name)
    sources = apply_home_guard(op, sources)
    ctx = _Ctx(op, world, sources, targets, tz, now or datetime.now(tz))
    for c in existing or []:
        ctx.existing.setdefault(c.target_id, []).append(c)
    arrivals = {}
    for t in targets:
        arrival = t.order.arrival or op.arrival
        arrivals[t.village.id] = (
            arrival.replace(tzinfo=tz) if arrival.tzinfo is None else arrival.astimezone(tz)
        )

    warnings = _input_warnings(ctx, arrivals)
    _add_candidates(ctx, arrivals)
    _add_budgets(ctx)
    _add_noble_ordering(ctx)
    _add_required_offs(ctx)
    _add_demands(ctx)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = 8
    status = solver.solve(ctx.model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        msg = f"Solver fand keine Lösung (Status {solver.status_name(status)})."
        raise RuntimeError(msg)
    if status == cp_model.FEASIBLE:
        warnings.append("Zeitlimit erreicht - Lösung ist gut, aber evtl. nicht optimal.")

    shortfalls = _explain_shortfalls(ctx, solver)
    warnings.extend(ctx.notes)
    for t in targets:
        brk = ctx.second_break.get(t.village.id)
        if brk is not None and solver.value(brk):
            warnings.append(
                f"{t.village.coord}: Sekunde gebrochen - Offs landen 1 s vor den AGs "
                "(in derselben Sekunde ließ sich keine Off vor allen AGs losschicken)."
            )
        fixed = ctx.existing.get(t.village.id, [])
        if fixed:
            warnings.append(
                f"{t.village.coord}: {len(fixed)} bestehende Angriffe aus dem DS-Ultimate-Plan "
                "berücksichtigt."
            )
            ours = arrivals[t.village.id]
            real = [c for c in fixed if c.type != CommandType.FAKE]
            other = sorted(
                {c.arrival for c in real if abs(c.arrival - ours) > timedelta(seconds=5)}
            )
            if other:
                times_txt = ", ".join(f"{a:%H:%M:%S}" for a in other)
                warnings.append(
                    f"{t.village.coord}: Wing landet um {times_txt}, Main um {ours:%H:%M:%S} - "
                    "Ankunftszeit prüfen!"
                )
        has_fixed_off = any(c.type in (CommandType.ATTACK, CommandType.WALLBREAKER) for c in fixed)
        if t.order.nobles and not t.order.offs and not has_fixed_off:
            warnings.append(
                f"{t.village.coord}: AGs gewünscht, aber keine Off (weder Main noch Wing) - "
                "ein AG ohne Off davor wird nie geplant."
            )
    for t, f, miss in ctx.uncovered_fixed_ags:
        if solver.value(miss):
            warnings.append(
                f"{t.village.coord}: Wing-AG von {f.note.split(' -> ')[0]} (Abschick "
                f"{f.send:%H:%M:%S}, Ankunft {f.arrival:%H:%M:%S}) hat KEINE Off davor!"
            )
    commands = _commands(ctx, solver)
    commands += _plan_supports(ctx, commands, warnings)
    commands.sort(key=lambda c: (c.send, c.source_id))
    plan = Plan(
        world=op.world,
        name=op.name,
        created_at=ctx.now,
        commands=commands,
        existing=existing or [],
        warnings=warnings + shortfalls,
    )
    return PlanResult(plan=plan, shortfalls=shortfalls)
