"""Use-case layer shared by the CLI and the MCP server."""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel

from ap_planner.checks import CheckReport, run_checks
from ap_planner.config import Settings
from ap_planner.domain import travel
from ap_planner.domain.night import in_night_bonus
from ap_planner.dsu import DSU_BASE, DsuClient, DsuPlanInfo
from ap_planner.export.announce import TargetInfo
from ap_planner.export.review import (
    group_by_player,
    kind_label,
    player_commands,
    review_markdown,
    safe_filename,
    target_filename,
)
from ap_planner.export.workbench import to_workbench, to_workbench_line
from ap_planner.ingest.store import WorldStore
from ap_planner.ingest.troops.overview_text import parse_overview_text, world_unit_columns
from ap_planner.ingest.world_client import FetchResult, WorldClient
from ap_planner.models.map import Coord, Village
from ap_planner.models.operation import DsuMode, DsuPlanLink, Operation, PlanKind, TargetOrder
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.profile import Profile, deep_merge
from ap_planner.models.troops import TroopSnapshot, VillageTroops
from ap_planner.models.world import Unit
from ap_planner.solver.planner import Source, Target, plan_operation, reserve_troops


def sync_world(settings: Settings, *, force: bool = False) -> list[FetchResult]:
    client = WorldClient(settings)
    try:
        results = client.fetch_all(force=force)
    finally:
        client.close()
    store = WorldStore.open(settings)
    try:
        store.load_raw(settings.raw_dir, settings.world)
    finally:
        store.close()
    return results


class WorldSummary(BaseModel):
    world: str
    speed: float
    unit_speed: float
    millis_arrival: bool
    attack_gap_ms: int
    night_bonus: str
    fake_limit_pct: float
    snob_max_dist: int
    knight: bool
    archer: bool
    minutes_per_field: dict[str, float]
    map_synced_at: str | None


def world_summary(store: WorldStore) -> WorldSummary:
    cfg = store.world_config()
    night = (
        f"{cfg.night.start_hour}:00-{cfg.night.end_hour}:00 (x{cfg.night.def_factor})"
        if cfg.night.active
        else "off"
    )
    return WorldSummary(
        world=cfg.world,
        speed=cfg.speed,
        unit_speed=cfg.unit_speed,
        millis_arrival=cfg.millis_arrival,
        attack_gap_ms=cfg.attack_gap_ms,
        night_bonus=night,
        fake_limit_pct=cfg.fake_limit_pct,
        snob_max_dist=cfg.snob_max_dist,
        knight=cfg.knight,
        archer=cfg.archer,
        minutes_per_field={u.value: i.speed for u, i in cfg.units.items()},
        map_synced_at=store.meta("map_synced_at"),
    )


def resolve_village(store: WorldStore, ref: str | int) -> Village:
    """Resolve a village id or ``x|y`` coordinate."""
    village: Village | None
    if isinstance(ref, int) or str(ref).strip().isdigit():
        village = store.village(int(ref))
    else:
        village = store.village_at(Coord.parse(str(ref)))
    if village is None:
        msg = f"Unknown village: {ref!r}"
        raise LookupError(msg)
    return village


@dataclass(frozen=True)
class TravelInfo:
    source: Village
    target: Village
    unit: Unit
    distance: float
    travel_seconds: int
    send: datetime | None
    arrival_in_night_bonus: bool | None


def travel_info(
    store: WorldStore,
    settings: Settings,
    source: str | int,
    target: str | int,
    unit: Unit,
    *,
    arrival: datetime | None = None,
) -> TravelInfo:
    cfg = store.world_config()
    src = resolve_village(store, source)
    tgt = resolve_village(store, target)
    dist = travel.distance(src.coord, tgt.coord)
    secs = travel.travel_seconds(dist, cfg.unit_speed_min(unit))
    send = night = None
    if arrival is not None:
        send = travel.send_time(cfg, src.coord, tgt.coord, unit, arrival)
        night = in_night_bonus(cfg.night, arrival, settings.timezone)
    return TravelInfo(src, tgt, unit, dist, secs, send, night)


def import_overview_text(store: WorldStore, text: str) -> list[VillageTroops]:
    """Parse text copied from Übersichten → Truppen and store it."""
    cfg = store.world_config()
    villages = parse_overview_text(text, world_unit_columns(list(cfg.units)))
    if not villages:
        msg = "No village rows found - copy the whole table incl. 'Name (x|y) Kxx' column."
        raise ValueError(msg)
    snapshot = TroopSnapshot(
        source="overview_paste", captured_at=datetime.now(UTC), villages=villages
    )
    return store.save_troops(snapshot)


def owner_name(store: WorldStore, village_id: int | None) -> str:
    """Owner of a village according to the map data ('?' if unknown)."""
    if village_id is None:
        return "?"
    village = store.village(village_id)
    if village is None:
        return "?"
    if village.player_id == 0:
        return "Barbar"
    player = store.player(village.player_id)
    return player.name if player else "?"


# --- operations ---------------------------------------------------------------


@dataclass(frozen=True)
class OperationOutput:
    folder: Path
    plan: Plan
    review: Path
    total: Path
    player_files: dict[str, Path]
    target_files: dict[str, Path]


def profile_path(world_dir: Path) -> Path:
    return world_dir / "profil.yaml"


def load_profile(world_dir: Path) -> Profile | None:
    path = profile_path(world_dir)
    if not path.exists():
        return None
    return Profile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def save_profile(profile: Profile, world_dir: Path) -> Path:
    path = profile_path(world_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = profile.model_dump(mode="json")
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load_operation(path: Path) -> Operation:
    """Load an operation; missing values come from the world's profile (data/<world>/profil.yaml).

    Layout: data/<world>/ops/<name>/operation.yaml -> profile in data/<world>/.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profile = load_profile(path.parent.parent.parent)
    if profile is not None:
        data = deep_merge(profile.operation_defaults(), data)
    return Operation.model_validate(data)


def save_operation(op: Operation, path: Path) -> None:
    data = op.model_dump(mode="json", exclude_defaults=False)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _sources(store: WorldStore, op: Operation) -> list[Source]:
    p = op.participants
    ally_ids = set()
    for tag in p.allies:
        ally = store.ally_by_tag(tag)
        if ally is None:
            msg = f"Unbekannter Stamm: {tag}"
            raise LookupError(msg)
        ally_ids.add(ally.id)
    wanted = {n.lower() for n in p.players}
    excluded = {n.lower() for n in p.exclude_players}
    excluded_villages = set(p.exclude_villages)
    sources: list[Source] = []
    for vt, _src, captured in store.troops():
        if vt.village_id is None or vt.coord in excluded_villages:
            continue
        village = store.village(vt.village_id)
        if village is None or village.player_id == 0:
            continue
        player = store.player(village.player_id)
        if player is None or player.name.lower() in excluded:
            continue
        if ally_ids and player.ally_id not in ally_ids:
            continue
        if wanted and player.name.lower() not in wanted:
            continue
        sources.append(Source(village, player.name, vt, datetime.fromisoformat(captured)))
    return sources


def _targets(store: WorldStore, op: Operation) -> list[Target]:
    targets: list[Target] = []
    for order in op.targets:
        village = store.village_at(order.coord)
        if village is None:
            msg = f"Ziel {order.coord} existiert nicht auf der Karte."
            raise LookupError(msg)
        targets.append(Target(order, village, owner_name(store, village.id)))
    return targets


def load_existing_commands(
    op: Operation, targets: list[Target], tz: str, client: DsuClient | None = None
) -> list[PlannedCommand]:
    """Read attacks on our targets from existing DS Ultimate plans (``dsu_plan``)."""
    by_link: dict[str, set[int]] = {}
    for t in targets:
        if t.order.dsu_plan:
            by_link.setdefault(t.order.dsu_plan, set()).add(t.village.id)
    if not by_link:
        return []
    dsu = client or DsuClient()
    try:
        out: list[PlannedCommand] = []
        for link, target_ids in by_link.items():
            out += [c for c in dsu.commands(link, tz) if c.target_id in target_ids]
        return out
    finally:
        if client is None:
            dsu.close()


def _split_existing(
    existing: list[PlannedCommand], targets: list[Target], own_ids: set[int]
) -> tuple[list[PlannedCommand], list[PlannedCommand], list[PlannedCommand]]:
    """(wing commands, own commands we keep, own commands replaced by new planning)."""
    order_of = {t.village.id: t.order for t in targets}
    wing: list[PlannedCommand] = []
    kept: list[PlannedCommand] = []
    dropped: list[PlannedCommand] = []
    for c in existing:
        if c.source_id not in own_ids:
            wing.append(c)
        elif order_of[c.target_id].dsu_mode == DsuMode.SPLIT:
            dropped.append(c)
        else:
            kept.append(c.model_copy(update={"origin": c.origin.replace("dsu:", "kept:")}))
    return wing, kept, dropped


def _remaining_demand(targets: list[Target], kept_own: list[PlannedCommand]) -> list[Target]:
    """Targets still to plan; kept own commands (merge) count towards the wanted numbers."""
    out: list[Target] = []
    for t in targets:
        if t.order.plans_nothing_new:
            continue
        mine = [c for c in kept_own if c.target_id == t.village.id]
        if mine:
            count = {ct: sum(1 for c in mine if c.type == ct) for ct in CommandType}
            fake_nobles = sum(
                1 for c in mine if c.type == CommandType.FAKE and c.slowest_unit == Unit.SNOB
            )
            order = t.order.model_copy(
                update={
                    "offs": max(0, t.order.offs - count[CommandType.ATTACK]),
                    "nobles": max(0, t.order.nobles - count[CommandType.CONQUEST]),
                    "fakes": max(0, t.order.fakes - (count[CommandType.FAKE] - fake_nobles)),
                    "fake_nobles": max(0, t.order.fake_nobles - fake_nobles),
                }
            )
            if (
                order.offs + order.nobles + order.fakes + order.fake_nobles == 0
                and not order.support
            ):
                continue
            out.append(Target(order, t.village, t.owner))
            continue
        out.append(t)
    return out


@dataclass(frozen=True)
class EnemyVillage:
    coord: str
    player: str
    tribe: str
    distance: float
    noble_seconds: int


def enemy_villages(store: WorldStore, target: Village, radius: float) -> list[EnemyVillage]:
    """Villages of the target's owner and tribe around the target (possible re-nobles)."""
    world = store.world_config()
    owner = store.player(target.player_id) if target.player_id else None
    if owner is None:
        return []
    tribe = store.conn.execute("SELECT tag FROM allies WHERE id = ?", (owner.ally_id,)).fetchone()
    tag = str(tribe["tag"]) if tribe else "-"
    rows: list[EnemyVillage] = []
    for v in store.villages_in_radius(target.coord, radius):
        if v.id == target.id or v.player_id == 0:
            continue
        p = store.player(v.player_id)
        if p is None or not (p.id == owner.id or (owner.ally_id and p.ally_id == owner.ally_id)):
            continue
        dist = travel.distance(v.coord, target.coord)
        if dist > world.snob_max_dist:
            continue
        secs = travel.travel_seconds(dist, world.unit_speed_min(Unit.SNOB))
        rows.append(EnemyVillage(str(v.coord), p.name, tag if p.ally_id else "-", dist, secs))
    return sorted(rows, key=lambda r: r.distance)


_MANUAL_TYPES = {
    "attack": CommandType.ATTACK,
    "fake": CommandType.FAKE,
    "support": CommandType.SUPPORT,
}


def manual_commands(
    store: WorldStore, op: Operation, targets: list[Target], tz: str
) -> tuple[list[PlannedCommand], list[str]]:
    """``manual_attacks``: compute runtime and send time for hand-set attacks."""
    world = store.world_config()
    zone = ZoneInfo(tz)
    out: list[PlannedCommand] = []
    notes: list[str] = []
    for t in targets:
        for m in t.order.manual_attacks:
            src = store.village_at(m.coord)
            if src is None:
                notes.append(f"Manueller Angriff: Dorf {m.coord} nicht auf der Karte.")
                continue
            arrival = m.arrival or t.order.arrival or op.arrival
            arrival = arrival.replace(tzinfo=zone) if arrival.tzinfo is None else arrival
            secs = travel.travel_seconds(
                travel.distance(src.coord, t.village.coord), world.unit_speed_min(m.slowest_unit)
            )
            send = arrival - timedelta(seconds=secs)
            player = owner_name(store, src.id)
            if send <= datetime.now(zone):
                notes.append(f"Manueller Angriff von {player} {m.coord} käme zu spät.")
                continue
            out.append(
                PlannedCommand(
                    source_id=src.id,
                    target_id=t.village.id,
                    source_player_id=src.player_id,
                    units=m.units,
                    slowest_unit=m.slowest_unit,
                    type=_MANUAL_TYPES[m.kind],
                    arrival=arrival,
                    send=send,
                    travel=timedelta(seconds=secs),
                    note=f"{player} -> {t.owner}",
                    origin="manual:",
                )
            )
    return out, notes


def redirect_wing_commands(
    store: WorldStore,
    op: Operation,
    targets: list[Target],
    tz: str,
    *,
    own_ids: set[int],
    client: DsuClient | None = None,
) -> tuple[list[PlannedCommand], list[str]]:
    """``wing_from``: move wing attacks from another target to ours (new runtime/send time)."""
    world = store.world_config()
    zone = ZoneInfo(tz)
    out: list[PlannedCommand] = []
    notes: list[str] = []
    jobs = [(t, r) for t in targets for r in t.order.wing_from]
    if not jobs:
        return out, notes
    dsu = client or DsuClient()
    try:
        for t, r in jobs:
            origin = store.village_at(r.coord)
            if origin is None:
                notes.append(f"Umleiten: Ziel {r.coord} nicht auf der Karte.")
                continue
            arrival = t.order.arrival or op.arrival
            arrival = arrival.replace(tzinfo=zone) if arrival.tzinfo is None else arrival
            for c in dsu.commands(r.dsu_plan, tz):
                if c.target_id != origin.id or c.source_id in own_ids:
                    continue
                src = store.village(c.source_id)
                if src is None:
                    continue
                secs = travel.travel_seconds(
                    travel.distance(src.coord, t.village.coord),
                    world.unit_speed_min(c.slowest_unit),
                )
                send = arrival - timedelta(seconds=secs)
                if send <= datetime.now(zone):
                    notes.append(f"Umleiten: {c.note.split(' -> ')[0]} {src.coord} käme zu spät.")
                    continue
                out.append(
                    c.model_copy(
                        update={
                            "target_id": t.village.id,
                            "arrival": arrival,
                            "send": send,
                            "travel": timedelta(seconds=secs),
                            "note": f"{c.note.split(' -> ')[0]} -> {t.owner}",
                            "origin": c.origin.replace("dsu:", "moved:"),
                        }
                    )
                )
    finally:
        if client is None:
            dsu.close()
    if out:
        notes.append(
            f"{len(out)} Wing-Angriffe umgeleitet - der Wing braucht die NEUEN Abschickzeiten "
            "(siehe Ziel-Plan)."
        )
    return out, notes


def solve_operation(
    store: WorldStore, settings: Settings, path: Path, *, now: datetime | None = None
) -> OperationOutput:
    """Plan the operation in ``path`` and write all outputs next to it."""
    op = load_operation(path)
    if op.world != settings.world:
        msg = f"Operation ist für {op.world}, aktive Welt ist {settings.world}."
        raise ValueError(msg)
    world = store.world_config()
    sources = _sources(store, op)
    if not sources:
        msg = "Keine Truppen für die Teilnehmer importiert - erst `ap troops import`."
        raise ValueError(msg)
    targets = _targets(store, op)
    existing = load_existing_commands(op, targets, settings.timezone)
    own_ids = {s.village.id for s in sources}
    wing, kept_own, dropped = _split_existing(existing, targets, own_ids)
    moved, moved_notes = redirect_wing_commands(
        store, op, targets, settings.timezone, own_ids=own_ids
    )
    wing += moved
    manual, manual_notes = manual_commands(store, op, targets, settings.timezone)
    wing += [c for c in manual if c.source_id not in own_ids]
    kept_own += [
        c.model_copy(update={"origin": "kept:manual"}) for c in manual if c.source_id in own_ids
    ]
    moved_notes += manual_notes
    sources, notes = reserve_troops(world, op, sources, kept_own)
    plan_targets = _remaining_demand(targets, kept_own)
    result = plan_operation(
        op,
        world,
        sources,
        plan_targets,
        tz_name=settings.timezone,
        now=now,
        existing=[*wing, *kept_own],
    )
    plan = result.plan.model_copy(update={"existing": [*wing, *kept_own]})
    plan.warnings.extend(notes + moved_notes)
    if kept_own:
        plan.warnings.append(
            f"{len(kept_own)} bestehende Main-Angriffe werden behalten (Truppen als verbraucht "
            "gerechnet, sie stehen auch in den Spieler-Plänen)."
        )
    if dropped:
        plan.warnings.append(
            f"{len(dropped)} alte Main-Angriffe aus Wing-Plänen werden durch die neue Planung "
            "ersetzt (Modus split)."
        )

    folder = path.parent
    coords = {s.village.id: str(s.village.coord) for s in sources}
    coords |= {t.village.id: str(t.village.coord) for t in targets}
    for c in plan.existing:
        if c.source_id not in coords and (v := store.village(c.source_id)) is not None:
            coords[c.source_id] = str(v.coord)
    (folder / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    (folder / ".solved_targets.json").write_text(
        json.dumps([t.model_dump(mode="json") for t in op.targets], sort_keys=True),
        encoding="utf-8",
    )
    review = folder / "review.md"
    extra = _enemy_sections(store, targets, plan, settings.timezone, sources)
    review.write_text(
        review_markdown(op, plan, coords, settings.timezone) + extra, encoding="utf-8"
    )
    total = folder / "gesamt_workbench.txt"
    total.write_text(to_workbench(plan.commands), encoding="utf-8")
    player_files = {
        player: _write(folder / "spieler" / f"{safe_filename(player)}.txt", cmds)
        for player, cmds in group_by_player(plan).items()
    }
    _clean(folder / "spieler", set(player_files.values()))
    target_files: dict[str, Path] = {}
    for t in targets:
        cmds = import_commands(plan, t.order, t.village.id)
        if cmds:
            name = target_filename(str(t.village.coord), t.owner)
            target_files[str(t.village.coord)] = _write(folder / "ziele" / f"{name}.txt", cmds)
    _clean(folder / "ziele", set(target_files.values()))
    return OperationOutput(folder, plan, review, total, player_files, target_files)


def _free_nobles(
    store: WorldStore, target: Village, plan: Plan, sources: list[Source]
) -> list[tuple[str, str, int, timedelta]]:
    """Own villages with AGs left after this plan, in noble range of the target."""
    world = store.world_config()
    used: dict[int, int] = {}
    for c in player_commands(plan):
        snobs = c.units.get(Unit.SNOB, 0)
        if c.type == CommandType.CONQUEST or c.slowest_unit == Unit.SNOB:
            snobs = max(1, snobs)  # hand-made plans sometimes omit the AG itself
        used[c.source_id] = used.get(c.source_id, 0) + snobs
    rows: list[tuple[str, str, int, timedelta]] = []
    for s in sources:
        free = s.troops.units.get(Unit.SNOB, 0) - used.get(s.village.id, 0)
        dist = travel.distance(s.village.coord, target.coord)
        if free <= 0 or dist > world.snob_max_dist:
            continue
        secs = travel.travel_seconds(dist, world.unit_speed_min(Unit.SNOB))
        rows.append((s.player, str(s.village.coord), free, timedelta(seconds=secs)))
    return sorted(rows, key=lambda r: r[3])


def _enemy_sections(
    store: WorldStore, targets: list[Target], plan: Plan, tz: str, sources: list[Source]
) -> str:
    """Re-noble threat analysis (+ own counter re-noble reserve) for support targets."""
    zone = ZoneInfo(tz)
    parts: list[str] = []
    for t in targets:
        if t.order.support is None:
            continue
        enemies = enemy_villages(store, t.village, t.order.support.enemy_radius)
        ags = [
            c
            for c in [*plan.commands, *plan.existing]
            if c.target_id == t.village.id and c.type == CommandType.CONQUEST
        ]
        supports = [
            c
            for c in plan.commands
            if c.target_id == t.village.id and c.type == CommandType.SUPPORT
        ]
        lines = ["", f"## Readel-Gefahr {t.village.coord} ({t.owner})"]
        if ags:
            last = max(ags, key=lambda c: (c.arrival, c.send))
            lines.append(
                f"Letzter AG landet {last.arrival.astimezone(zone):%H:%M:%S} "
                f"(abgeschickt {last.send.astimezone(zone):%H:%M:%S})."
            )
            if enemies:
                fastest = enemies[0]
                react = last.arrival + timedelta(seconds=fastest.noble_seconds)
                lines.append(
                    f"Schnellstes gegnerisches Readel als Reaktion: aus {fastest.coord} "
                    f"({fastest.player}), AG-Laufzeit {timedelta(seconds=fastest.noble_seconds)}"
                    f" -> frühestens {react.astimezone(zone):%H:%M:%S}. Vorgetimte Readel-AGs "
                    "können schon in der Sekunde nach dem letzten AG landen."
                )
            if supports:
                first = min(supports, key=lambda c: (c.arrival, c.send))
                lines.append(
                    f"Erste Unterstützung landet {first.arrival.astimezone(zone):%H:%M:%S} "
                    f"(abgeschickt {first.send.astimezone(zone):%H:%M:%S}, nach dem letzten AG)."
                )
        lines += [
            "",
            "| Dorf | Spieler | Stamm | Entfernung | AG-Laufzeit |",
            "|---|---|---|---|---|",
            *(
                f"| {e.coord} | {e.player} | {e.tribe} | {e.distance:.1f} "
                f"| {timedelta(seconds=e.noble_seconds)} |"
                for e in enemies[:15]
            ),
        ]
        if len(enemies) > 15:
            lines.append(f"... und {len(enemies) - 15} weitere Dörfer in Reichweite.")
        reserve = _free_nobles(store, t.village, plan, sources)
        lines += ["", f"### Eigene Readel-Reserve für {t.village.coord}"]
        if reserve:
            lines += [
                "Freie AGs nach diesem Plan (Konter-Readel, falls der Gegner zurückadelt):",
                "",
                "| Spieler | Dorf | freie AGs | AG-Laufzeit |",
                "|---|---|---|---|",
                *(f"| {p} | {c} | {n} | {d} |" for p, c, n, d in reserve),
            ]
        else:
            lines.append("_Keine freien AGs in Reichweite - ein Konter-Readel wäre nicht möglich!_")
        parts.append("\n".join(lines))
    return "\n".join(parts) + ("\n" if parts else "")


def _write(path: Path, commands: list[PlannedCommand]) -> Path:
    path.parent.mkdir(exist_ok=True)
    path.write_text(to_workbench(commands), encoding="utf-8")
    return path


def _clean(folder: Path, keep: set[Path]) -> None:
    """Remove outputs of earlier runs that no longer exist (e.g. a dropped player)."""
    for old in folder.glob("*.txt"):
        if old not in keep:
            old.unlink()


# --- DS Ultimate plans (manual creation, one per target or player) -----------------


def dsu_create_url(world: str) -> str:
    """URL that creates a new, empty DS Ultimate attack plan, e.g. .../de/260."""
    m = re.fullmatch(r"([a-z]+)(\w+)", world)
    if m is None:
        msg = f"Unbekanntes Weltformat: {world}"
        raise ValueError(msg)
    return f"{DSU_BASE}/tools/create/attackPlanner/{m[1]}/{m[2]}"


@dataclass(frozen=True)
class DsuGroup:
    kind: PlanKind
    key: str
    title: str
    commands: list[PlannedCommand]
    # Edit link of an existing (wing) plan to import into instead of creating a new one.
    existing_plan: str | None = None

    @property
    def workbench(self) -> str:
        return to_workbench(self.commands)


def load_plan(op_path: Path) -> Plan:
    plan_file = op_path.parent / "plan.json"
    if not plan_file.exists():
        msg = "Noch kein Plan berechnet - erst `ap op solve`."
        raise FileNotFoundError(msg)
    return Plan.model_validate_json(plan_file.read_text(encoding="utf-8"))


def dsu_groups(store: WorldStore, op: Operation, plan: Plan, kind: PlanKind) -> list[DsuGroup]:
    if kind == "player":
        return [
            DsuGroup(
                "player", player, f"ANGRIFFE {min(c.arrival for c in cmds):%d.%m.} | {player}", cmds
            )
            for player, cmds in group_by_player(plan).items()
        ]
    groups: list[DsuGroup] = []
    for t in op.targets:
        village = store.village_at(t.coord)
        if village is None:
            continue
        cmds = import_commands(plan, t, village.id)
        if not cmds:
            continue
        owner = owner_name(store, village.id)
        title = target_plan_title(cmds, str(t.coord), owner)
        into = t.dsu_plan if t.dsu_mode == DsuMode.MERGE else None
        groups.append(DsuGroup("target", str(t.coord), title, cmds, into))
    return groups


def attack_label(cmds: list[PlannedCommand]) -> str:
    """ADELN (real AGs land), OFF (real offs, no AG), DEFF (only support) or FAKE."""
    types = {c.type for c in cmds}
    if CommandType.CONQUEST in types:
        return "ADELN"
    if types & {CommandType.ATTACK, CommandType.WALLBREAKER}:
        return "OFF"
    if types and types <= {
        CommandType.SUPPORT,
        CommandType.STAND_SUPPORT,
        CommandType.FAST_SUPPORT,
    }:
        return "DEFF"
    return "FAKE"


def target_plan_title(cmds: list[PlannedCommand], coord: str, owner: str) -> str:
    """e.g. 'ADELN 07.11. | Ziel 481|532 Baraxdihut' - the kind of attack comes first."""
    day = min(c.arrival for c in cmds).strftime("%d.%m.") if cmds else ""
    return f"{attack_label(cmds)} {day} | Ziel {coord} {owner}".replace("  ", " ")


def import_commands(plan: Plan, order: TargetOrder, target_id: int) -> list[PlannedCommand]:
    """What goes into the DS Ultimate plan for one target, depending on ``dsu_mode``."""
    new = [c for c in plan.commands if c.target_id == target_id]
    fixed = [c for c in plan.existing if c.target_id == target_id]
    moved = [c for c in fixed if c.origin.startswith(("moved:", "manual:", "kept:manual"))]
    if order.dsu_plan is None or order.dsu_mode == DsuMode.MERGE:
        cmds = [*moved, *new] if order.dsu_plan is None else new
    elif order.dsu_mode == DsuMode.SPLIT:
        cmds = [*(c for c in fixed if c.origin.startswith("dsu:")), *new]
    elif order.dsu_mode == DsuMode.COPY:
        cmds = fixed
    else:  # KEEP: the existing plan stays as it is
        cmds = []
    return sorted(cmds, key=lambda c: (c.arrival, c.send))


def check_dsu_plan(
    op: Operation, group: DsuGroup, info: DsuPlanInfo, baseline: int = 0
) -> list[str]:
    """Problems with a DS Ultimate plan after our import (empty list = all good).

    ``baseline`` = attacks that were already in the plan before (wing plan).
    """
    problems: list[str] = []
    expected = baseline + len(group.commands)
    if group.existing_plan:
        if info.item_count == baseline:
            problems.append("Keine neuen Angriffe im Plan - der Import fehlt oder schlug fehl.")
        elif info.item_count != expected:
            problems.append(
                f"Im Plan sind {info.item_count} Angriffe, erwartet {baseline} (vorher) + "
                f"{len(group.commands)} (Main) = {expected}."
            )
        return problems
    other = next(
        (
            x
            for x in op.dsu_links
            if x.plan_id == info.plan_id and not (x.kind == group.kind and x.key == group.key)
        ),
        None,
    )
    if other is not None:
        problems.append(
            f"Plan {info.plan_id} ist schon für {other.key} gespeichert - bitte einen neuen Plan "
            "anlegen (vorher dem alten Plan einen Titel geben)."
        )
    if not info.has_title:
        problems.append(
            "Der Plan hat keinen Titel. Bitte Titel setzen - sonst öffnet DS Ultimate beim "
            "nächsten Plan wieder diesen hier."
        )
    if info.item_count == 0:
        problems.append("Der Plan ist leer - der Workbench-Import fehlt oder ist fehlgeschlagen.")
    elif info.item_count != len(group.commands):
        problems.append(
            f"Im Plan sind {info.item_count} Angriffe, erwartet {len(group.commands)} "
            "(doppelt importiert oder falscher Text?)."
        )
    return problems


def add_dsu_link(op: Operation, group: DsuGroup, info: DsuPlanInfo) -> Operation:
    links = [x for x in op.dsu_links if not (x.kind == group.kind and x.key == group.key)]
    links.append(
        DsuPlanLink(
            kind=group.kind,
            key=group.key,
            title=info.title or group.title,
            plan_id=info.plan_id,
            show_link=info.show_link,
            edit_link=info.edit_link,
        )
    )
    return op.model_copy(update={"dsu_links": links})


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard (X11/Wayland). Returns False if not possible."""
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        cmd = ["wl-copy"]
    elif shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif shutil.which("pbcopy"):
        cmd = ["pbcopy"]
    else:
        return False
    try:
        subprocess.run(cmd, input=text.encode(), check=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def target_infos(store: WorldStore, op: Operation) -> list[TargetInfo]:
    """Village name, owner and tribe tag per target (for announcements)."""
    out: list[TargetInfo] = []
    for t in op.targets:
        v = store.village_at(t.coord)
        if v is None:
            continue
        owner = store.player(v.player_id) if v.player_id else None
        tribe = "-"
        if owner and owner.ally_id:
            row = store.conn.execute("SELECT tag FROM allies WHERE id = ?", (owner.ally_id,))
            hit = row.fetchone()
            tribe = str(hit["tag"]) if hit else "-"
        out.append(TargetInfo(str(t.coord), v.id, v.name, owner.name if owner else "Barbar", tribe))
    return out


def check_operation(
    store: WorldStore, settings: Settings, path: Path, *, with_dsu: bool = False
) -> CheckReport:
    """Automated review of the planned operation (see ``ap_planner.checks``)."""
    op = load_operation(path)
    plan = load_plan(path)
    world = store.world_config()
    sources = _sources(store, op)
    coords = {v.id: str(v.coord) for t in op.targets if (v := store.village_at(t.coord))}
    report = run_checks(
        op,
        plan,
        world,
        sources,
        coords,
        now=datetime.now(ZoneInfo(settings.timezone)),
        tz=settings.timezone,
    )
    if plan_is_outdated(path):
        report.warnings.insert(0, "operation.yaml ist neuer als der Plan - erst `ap op solve`.")
    _check_against_profile(report, op, load_profile(path.parent.parent.parent))
    if with_dsu:
        _check_dsu_sync(report, store, op, plan)
    return report


def plan_is_outdated(path: Path) -> bool:
    plan_file = path.parent / "plan.json"
    if not plan_file.exists():
        return True
    # dsu link updates touch operation.yaml without changing the plan -> compare targets only
    stamp = path.parent / ".solved_targets.json"
    if not stamp.exists():
        return False
    targets = [t.model_dump(mode="json") for t in load_operation(path).targets]
    return stamp.read_text(encoding="utf-8") != json.dumps(targets, sort_keys=True)


def _check_dsu_sync(report: CheckReport, store: WorldStore, op: Operation, plan: Plan) -> None:
    """Do the DS Ultimate plans contain exactly the planned commands? Lists the exact fixes."""

    def key(c: PlannedCommand) -> tuple[int, int, int, str, str]:
        return (
            c.source_id,
            c.target_id,
            int(c.type),
            c.arrival.replace(microsecond=0).isoformat(),
            c.send.replace(microsecond=0).isoformat(),
        )

    def describe(c: PlannedCommand) -> str:
        src = store.village(c.source_id)
        tgt = store.village(c.target_id)
        return (
            f"{kind_label(c)} {src.coord if src else c.source_id} -> "
            f"{tgt.coord if tgt else c.target_id}, Ankunft {c.arrival:%d.%m. %H:%M:%S}"
        )

    dsu = DsuClient()
    try:
        for kind in ("target", "player"):
            for g in dsu_groups(store, op, plan, kind):
                link = op.dsu_link(kind, g.key)
                label = "Ziel" if kind == "target" else "Spieler"
                if link is None:
                    report.warnings.append(f"DS Ultimate {label} {g.key}: noch kein Plan angelegt.")
                    continue
                there = dsu.commands(link.edit_link or link.show_link)
                have = {key(c) for c in there}
                want = {key(c) for c in g.commands}
                missing = [c for c in g.commands if key(c) not in have]
                extra = [] if g.existing_plan else [c for c in there if key(c) not in want]
                if not missing and not extra:
                    report.ok.append(f"DS Ultimate {label} {g.key}: Plan {link.plan_id} stimmt.")
                    continue
                lines = [
                    f"DS Ultimate {label} {g.key} (Plan {link.plan_id}) weicht ab:",
                    *(f"  - LÖSCHEN: {describe(c)}" for c in extra),
                    *(f"  - HINZUFÜGEN: {describe(c)}" for c in missing),
                ]
                if missing:
                    lines.append("  - Workbench-Zeilen zum Hinzufügen:")
                    lines += [f"    `{to_workbench_line(c)}`" for c in missing]
                report.errors.append("\n".join(lines))
    finally:
        dsu.close()


def _check_against_profile(report: CheckReport, op: Operation, profile: Profile | None) -> None:
    """Point out where the operation deviates from the player's profile."""
    if profile is None:
        report.warnings.append("Kein Profil (data/<welt>/profil.yaml) - `ap init` ausführen.")
        return
    diffs: list[str] = []
    if profile.own_tribes and set(op.participants.allies) != set(profile.own_tribes):
        diffs.append(f"Teilnehmer {op.participants.allies} statt {profile.own_tribes}")
    if op.home_guard != profile.home_guard:
        diffs.append("anderer Fakeschutz")
    if op.off_settings.min_pop != profile.off_min_pop:
        diffs.append(f"volle Off ab {op.off_settings.min_pop} statt {profile.off_min_pop}")
    if op.send_window != profile.send_window:
        diffs.append("anderes Losschick-Fenster")
    if diffs:
        report.warnings.append("Abweichung vom Profil: " + "; ".join(diffs) + " (gewollt?)")
    else:
        report.ok.append("Operation entspricht den Vorgaben im Profil.")
