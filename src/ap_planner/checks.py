"""Automated review of a planned operation: double booking, ordering rule, free troops."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ap_planner.domain.morale import attack_blocked, morale_pct, point_ratio
from ap_planner.domain.night import in_night_bonus
from ap_planner.export.review import is_wing, kind_label, player_commands
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit, WorldConfig
from ap_planner.solver.planner import Source, _estimate_units, _pop

OFFS = (CommandType.ATTACK, CommandType.WALLBREAKER)
SUPPORTS = (CommandType.SUPPORT, CommandType.STAND_SUPPORT, CommandType.FAST_SUPPORT)
DEFF_UNITS = (Unit.SPEAR, Unit.SWORD, Unit.ARCHER, Unit.HEAVY)
UNIT_DE = {
    "spear": "Speer", "sword": "Schwert", "axe": "Axt", "spy": "Späher", "light": "LKav",
    "heavy": "SKav", "ram": "Ramme", "catapult": "Kata", "snob": "AG", "archer": "Bogen",
    "marcher": "BB", "knight": "Pala",
}  # fmt: skip


@dataclass
class CheckReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    free: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)

    def markdown(self, title: str) -> str:
        lines = [f"# Automatischer Review: {title}", ""]
        verdict = "❌ Fehler gefunden" if self.errors else "✅ Keine Fehler"
        lines += [f"**{verdict}** ({len(self.errors)} Fehler, {len(self.warnings)} Hinweise)", ""]
        for head, items in (
            ("Fehler (müssen behoben werden)", self.errors),
            ("Hinweise", self.warnings),
            ("Freie Truppen nach diesem Plan", self.free),
            ("Bestanden", self.ok),
        ):
            if items:
                lines += [f"## {head}", *(f"- {i}" for i in items), ""]
        return "\n".join(lines)


def _units_de(units: dict[Unit, int]) -> str:
    return ", ".join(f"{n} {UNIT_DE.get(u.value, u.value)}" for u, n in units.items() if n)


def _usage(
    world: WorldConfig, op: Operation, sources: dict[int, Source], cmds: list[PlannedCommand]
) -> tuple[dict[int, dict[Unit, int]], set[tuple[int, Unit]]]:
    """Units per village, and which (village, unit) contain estimates (plans without units)."""
    used: dict[int, dict[Unit, int]] = defaultdict(lambda: defaultdict(int))
    estimated: set[tuple[int, Unit]] = set()
    for c in cmds:
        src = sources.get(c.source_id)
        units = _estimate_units(world, op, src, c) if src else dict(c.units)
        if not c.units:
            estimated |= {(c.source_id, u) for u in units}
        if c.type == CommandType.CONQUEST or c.slowest_unit == Unit.SNOB:
            units[Unit.SNOB] = max(1, units.get(Unit.SNOB, 0))
        for u, n in units.items():
            used[c.source_id][u] += n
    return used, estimated


def check_troops(
    report: CheckReport,
    world: WorldConfig,
    op: Operation,
    sources: dict[int, Source],
    cmds: list[PlannedCommand],
) -> dict[int, dict[Unit, int]]:
    """Double booking: more units planned than the village has (incl. fake protection)."""
    used, estimated = _usage(world, op, sources, cmds)
    problems = 0
    for sid, units in used.items():
        src = sources.get(sid)
        if src is None:
            report.warnings.append(
                f"Dorf {sid}: Befehle geplant, aber keine Truppendaten importiert."
            )
            continue
        have = src.troops.units
        over = {u: n - have.get(u, 0) for u, n in units.items() if n > have.get(u, 0)}
        guard = {
            u: n + op.home_guard.get(u, 0) - have.get(u, 0)
            for u, n in units.items()
            if u not in over and n + op.home_guard.get(u, 0) > have.get(u, 0) and n > 0
        }
        where = f"{src.player} {src.village.coord}"
        sure = {u: n for u, n in over.items() if (sid, u) not in estimated}
        guessed = {u: n for u, n in over.items() if (sid, u) in estimated}
        if sure:
            problems += 1
            kind = "AGs" if Unit.SNOB in sure else "Truppen"
            report.errors.append(
                f"Doppelt verplant ({kind}): {where} - es fehlen {_units_de(sure)}."
            )
        if guessed:
            report.warnings.append(
                f"Evtl. doppelt verplant: {where} - geschätzt fehlen {_units_de(guessed)} "
                "(Handplan ohne Truppenzahlen, bitte prüfen)."
            )
        if guard:
            report.warnings.append(
                f"Fakeschutz unterschritten: {where} - {_units_de(guard)} zu wenig."
            )
    if not problems:
        report.ok.append(f"Keine doppelte Zuweisung in {len(used)} Dörfern (Truppen und AGs).")
    return used


# An off only clears the way if it lands shortly before the AG; otherwise the enemy can
# restack deff in between.
OFF_COVER_WINDOW = timedelta(seconds=60)


def check_ordering(report: CheckReport, op: Operation, plan: Plan, coords: dict[int, str]) -> None:
    """Every AG needs an off landing before it; supports never before the last AG."""
    gap = timedelta(seconds=op.off_send_gap_s)
    by_target: dict[int, list[PlannedCommand]] = defaultdict(list)
    for c in [*player_commands(plan), *(c for c in plan.existing if is_wing(c))]:
        by_target[c.target_id].append(c)
    bad = 0
    for tid, cmds in by_target.items():
        offs = [c for c in cmds if c.type in OFFS]
        # Fake AGs carry a real nobleman too: same rule.
        ags = [c for c in cmds if c.type == CommandType.CONQUEST or c.slowest_unit == Unit.SNOB]
        where = coords.get(tid, str(tid))
        for ag in ags:
            covered = any(
                (ag.arrival - OFF_COVER_WINDOW <= o.arrival < ag.arrival)
                or (o.arrival == ag.arrival and o.send <= ag.send - gap)
                for o in offs
            )
            if not covered:
                bad += 1
                report.errors.append(
                    f"{where}: AG von {ag.note.split(' -> ')[0]} (ab {ag.send:%H:%M:%S}, an "
                    f"{ag.arrival:%H:%M:%S}) hat KEINE Off davor (höchstens "
                    f"{OFF_COVER_WINDOW.seconds} s vorher)."
                )
        for o in offs:  # own offs landing after own AGs in the same second do not clear
            if is_wing(o) or o.role == "tab":  # tab offs land between the AGs on purpose
                continue
            late = [
                a
                for a in ags
                if a.arrival == o.arrival and not is_wing(a) and o.send > a.send - gap
            ]
            if late:
                report.warnings.append(
                    f"{where}: Off von {o.note.split(' -> ')[0]} landet nach "
                    f"{len(late)} eigenen AG(s) in derselben Sekunde."
                )
        if ags:
            last = max(ags, key=lambda c: (c.arrival, c.send))
            for s in (c for c in cmds if c.type in SUPPORTS):
                if s.arrival < last.arrival or (s.arrival == last.arrival and s.send < last.send):
                    bad += 1
                    report.errors.append(
                        f"{where}: Unterstützung von {s.note.split(' -> ')[0]} landet VOR dem "
                        "letzten AG - sie würde den Gegner verteidigen!"
                    )
    if not bad:
        report.ok.append(
            f"Reihenfolge-Regel eingehalten auf {sum(1 for c in by_target.values() if c)} Zielen "
            "(kein AG ohne Off davor, keine Unterstützung vor dem letzten AG)."
        )


def check_times(
    report: CheckReport,
    world: WorldConfig,
    op: Operation,
    plan: Plan,
    sources: dict[int, Source],
    *,
    now: datetime,
    tz: str,
) -> None:
    zone = ZoneInfo(tz)
    mine = player_commands(plan)
    past = [c for c in mine if c.send <= now and not c.origin.endswith("manual:running")]
    for c in sorted(past, key=lambda c: c.send):
        report.errors.append(
            f"Abschickzeit vorbei: {c.note.split(' -> ')[0]} {kind_label(c)} um "
            f"{c.send.astimezone(zone):%d.%m. %H:%M:%S}."
        )
    soon = [c for c in mine if now < c.send <= now + timedelta(hours=1)]
    if soon:
        first = min(soon, key=lambda c: c.send)
        report.warnings.append(
            f"{len(soon)} Befehle müssen in der nächsten Stunde raus - der erste um "
            f"{first.send.astimezone(zone):%H:%M:%S} ({first.note.split(' -> ')[0]})."
        )
    night = {
        c.arrival
        for c in mine
        if c.type != CommandType.FAKE and in_night_bonus(world.night, c.arrival, tz)
    }
    for a in sorted(night):
        report.warnings.append(f"Ankunft {a.astimezone(zone):%d.%m. %H:%M:%S} liegt im Nachtbonus.")
    max_age = timedelta(hours=op.max_troop_age_hours)
    old = [
        s
        for sid, s in sources.items()
        if now - s.captured_at > max_age and sid in {c.source_id for c in mine}
    ]
    if old:
        report.warnings.append(
            f"Truppendaten älter als {op.max_troop_age_hours} h bei {len(old)} eingeplanten "
            "Dörfern - vor dem Losschicken neu importieren."
        )
    if not past:
        report.ok.append(f"Alle {len(mine)} Main-Befehle liegen in der Zukunft.")


ATTACKS = (*OFFS, CommandType.CONQUEST, CommandType.FAKE)


def check_morale_ratio(
    report: CheckReport,
    world: WorldConfig,
    op: Operation,
    plan: Plan,
    *,
    points: dict[int, tuple[str, int]],
    coords: dict[int, str],
    ratio_protected: frozenset[str],
) -> None:
    """10:1 point-ratio protection (attack impossible) and morale (weaker offs).

    ``points``: village id -> (owner name, owner points); barbarians have 0 points.
    """
    blocked: set[tuple[str, str]] = set()
    weak = 0
    cmds = [*player_commands(plan), *(c for c in plan.existing if is_wing(c))]
    for c in sorted(cmds, key=lambda c: (c.target_id, c.send)):
        if c.type not in ATTACKS:
            continue
        att_name, att = points.get(c.source_id, ("?", 0))
        def_name, dfd = points.get(c.target_id, ("?", 0))
        where = coords.get(c.target_id, str(c.target_id))
        active = att_name in ratio_protected or def_name in ratio_protected
        if attack_blocked(world, att, dfd, active=active):
            if (att_name, where) not in blocked:
                blocked.add((att_name, where))
                report.errors.append(
                    f"{where}: {att_name} ({att:,} P) kann {def_name} ({dfd:,} P) nicht "
                    f"angreifen - Punkteverhältnis {point_ratio(att, dfd):.1f}:1 über "
                    f"{world.newbie_ratio:g}:1 (Schutz der ersten {world.newbie_ratio_days} "
                    "Tage eines Accounts).".replace(",", ".")
                )
            continue
        pct = morale_pct(world, att, dfd)
        if pct >= 100 or c.type not in (*OFFS, CommandType.CONQUEST):
            continue
        weak += 1
        pop = _pop(world, {u: c.units.get(u, 0) for u in op.off_settings.units})
        what = "AG-Begleitschutz" if c.type == CommandType.CONQUEST else "Off"
        effect = f" - wirkt wie {pop * pct // 100:,} statt {pop:,} Plätze" if pop else ""
        report.warnings.append(
            f"{where}: Moral {pct} % für {what} von {att_name} ({att:,} P gegen {def_name} "
            f"{dfd:,} P){effect}.".replace(",", ".")
        )
    if ratio_protected and not blocked:
        report.ok.append(
            f"Kein Angriff über dem Punkteverhältnis {world.newbie_ratio:g}:1 (Neulingsschutz)."
        )
    if world.moral and not weak:
        report.ok.append("Alle Offs und AGs kämpfen mit 100 % Moral.")


def check_free(
    report: CheckReport,
    world: WorldConfig,
    op: Operation,
    sources: dict[int, Source],
    used: dict[int, dict[Unit, int]],
) -> None:
    """Troops that are still at home after this plan (offs, AGs, deff)."""
    rows: list[tuple[int, str]] = []
    for sid, s in sources.items():
        left = {
            u: n - used.get(sid, {}).get(u, 0) - op.home_guard.get(u, 0)
            for u, n in s.troops.units.items()
        }
        left = {u: n for u, n in left.items() if n > 0}
        off = _pop(world, {u: left.get(u, 0) for u in op.off_settings.units})
        deff = _pop(world, {u: left.get(u, 0) for u in DEFF_UNITS})
        parts: list[str] = []
        if off >= op.off_settings.fusion_min_pop:
            full = " (volle Off)" if off >= op.off_settings.min_pop else ""
            parts.append(f"Off {off} Plätze{full}")
        if left.get(Unit.SNOB, 0):
            parts.append(f"{left[Unit.SNOB]} AG")
        if deff >= 1000:
            parts.append(f"Deff {deff} Plätze")
        if parts:
            rows.append(
                (
                    off + 10_000 * left.get(Unit.SNOB, 0),
                    f"{s.player} {s.village.coord}: {', '.join(parts)}",
                )
            )
    report.free += [r for _, r in sorted(rows, key=lambda r: -r[0])]
    if not rows:
        report.ok.append("Alle nennenswerten Truppen sind verplant.")


def run_checks(
    op: Operation,
    plan: Plan,
    world: WorldConfig,
    sources: list[Source],
    coords: dict[int, str],
    *,
    now: datetime,
    tz: str = "Europe/Berlin",
    points: dict[int, tuple[str, int]] | None = None,
    ratio_protected: frozenset[str] = frozenset(),
) -> CheckReport:
    report = CheckReport()
    by_id = {s.village.id: s for s in sources}
    used = check_troops(report, world, op, by_id, player_commands(plan))
    check_ordering(report, op, plan, coords)
    check_times(report, world, op, plan, by_id, now=now, tz=tz)
    if points is not None:
        check_morale_ratio(
            report, world, op, plan, points=points, coords=coords, ratio_protected=ratio_protected
        )
    check_free(report, world, op, by_id, used)
    return report
