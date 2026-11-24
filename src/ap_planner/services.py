"""Use-case layer shared by the CLI and the MCP server."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import yaml
from pydantic import BaseModel

from ap_planner.checks import CheckReport, run_checks
from ap_planner.config import Settings
from ap_planner.domain import strategy, travel
from ap_planner.domain.battle import Wave
from ap_planner.domain.morale import morale_pct, ratio_protected
from ap_planner.domain.night import in_night_bonus
from ap_planner.domain.returns import ReturnTrip
from ap_planner.dsu import DSU_BASE, DsuClient, DsuLinkError, DsuPlanInfo
from ap_planner.dsu_api import DsuApiClient, DsuApiError
from ap_planner.dsu_web import DsuWebClient, EditablePlan
from ap_planner.export import gdoc
from ap_planner.export.announce import TargetInfo
from ap_planner.export.gdoc_api import rewrite_requests
from ap_planner.export.returns import plan_returns, returns_json, returns_markdown
from ap_planner.export.review import (
    group_by_player,
    is_wing,
    kind_label,
    player_commands,
    review_markdown,
    safe_filename,
    target_filename,
)
from ap_planner.export.workbench import to_workbench, to_workbench_line
from ap_planner.ingest.store import WorldStore
from ap_planner.ingest.troops.overview_text import parse_overview_text, world_unit_columns
from ap_planner.ingest.troops.script_json import looks_like_script_json, parse_script_json
from ap_planner.ingest.world_client import FetchResult, WorldClient
from ap_planner.models.map import Coord, Village
from ap_planner.models.operation import (
    DsuMode,
    DsuPlanLink,
    Operation,
    PlanKind,
    Status,
    TargetOrder,
)
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.profile import Profile, deep_merge
from ap_planner.models.troops import TroopSnapshot, VillageTroops
from ap_planner.models.world import Unit, WorldConfig
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
    """Parse text copied from Übersichten → Truppen (or the export of our in-game script)
    and store it."""
    if looks_like_script_json(text):
        rows, created, world = parse_script_json(text)
        cfg = store.world_config()
        if world and world != cfg.world:
            msg = f"Der Skript-Export ist von Welt {world}, eingerichtet ist {cfg.world}."
            raise ValueError(msg)
        if not rows:
            msg = (
                "Der Skript-Export enthält keine Dörfer - teilen die Mitglieder ihre Truppen "
                "mit dem Stamm?"
            )
            raise ValueError(msg)
        snapshot = TroopSnapshot(
            source="ap-troops-script", captured_at=created or datetime.now(UTC), villages=rows
        )
        return store.save_troops(snapshot)
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


def write_env(values: dict[str, str], path: Path = Path(".env")) -> None:
    """Set keys in .env (in the current folder), keep all other lines."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keep = [ln for ln in lines if ln.split("=", 1)[0].strip() not in values]
    keep += [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(keep) + "\n", encoding="utf-8")


def profile_path(world_dir: Path) -> Path:
    return world_dir / "profil.yaml"


def load_profile(world_dir: Path) -> Profile | None:
    path = profile_path(world_dir)
    if not path.exists():
        return None
    return Profile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def tribe_tags(world_dir: Path) -> list[str]:
    """Own tribe + wing from the profile: their Discord roles are pinged in the announcement."""
    profile = load_profile(world_dir)
    if profile is None:
        return []
    return list(dict.fromkeys([*profile.own_tribes, *profile.allied_tribes]))


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
        sources.append(
            Source(village, player.name, vt, datetime.fromisoformat(captured), player.points)
        )
    return sources


def _targets(store: WorldStore, op: Operation) -> list[Target]:
    targets: list[Target] = []
    for order in op.targets:
        village = store.village_at(order.coord)
        if village is None:
            msg = f"Ziel {order.coord} existiert nicht auf der Karte."
            raise LookupError(msg)
        owner = store.player(village.player_id) if village.player_id else None
        targets.append(
            Target(order, village, owner_name(store, village.id), owner.points if owner else 0)
        )
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
            out.append(replace(t, order=order))
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


def own_villages(store: WorldStore, tribes: list[str]) -> list[strategy.OwnVillage]:
    """Our villages with imported troops (owner in one of ``tribes``), for strategy questions."""
    ally_ids = {a.id for t in tribes if (a := store.ally_by_tag(t)) is not None}
    out: list[strategy.OwnVillage] = []
    for troops, _source, _captured in store.troops():
        if troops.village_id is None:
            continue
        village = store.village(troops.village_id)
        owner = store.player(village.player_id) if village and village.player_id else None
        if village is None or owner is None or owner.ally_id not in ally_ids:
            continue
        out.append(strategy.OwnVillage(village, owner.name, owner.points, dict(troops.units)))
    return out


def strategy_candidates(store: WorldStore, enemy: str) -> list[strategy.Candidate]:
    """All villages of an enemy tribe (tag or name) or player, with the villages that could
    send a noble back (the owner's whole tribe)."""
    ally = store.ally_by_tag(enemy)
    if ally is not None:
        villages = store.villages_of_ally(ally.id)
    else:
        player = store.player_by_name(enemy)
        if player is None:
            msg = (
                f"Kein Stamm und kein Spieler {enemy!r} gefunden (Tag, Stammes- oder Spielername)."
            )
            raise LookupError(msg)
        villages = store.villages_of_player(player.id)
    back: dict[int, list[Village]] = {}
    out: list[strategy.Candidate] = []
    for v in villages:
        owner = store.player(v.player_id)
        if owner is None:
            continue
        key = owner.ally_id or -owner.id
        if key not in back:
            back[key] = (
                store.villages_of_ally(owner.ally_id)
                if owner.ally_id
                else store.villages_of_player(owner.id)
            )
        tag = "-"
        if owner.ally_id:
            row = store.conn.execute("SELECT tag FROM allies WHERE id = ?", (owner.ally_id,))
            hit = row.fetchone()
            tag = str(hit["tag"]) if hit else "-"
        out.append(strategy.Candidate(v, owner.name, tag, owner.points, back[key]))
    return out


def strategy_targets(
    store: WorldStore,
    profile: Profile | None,
    enemy: str,
    *,
    max_hours: float = 12,
    deff_min_pop: int = 2000,
    limit: int = 15,
) -> tuple[list[strategy.TargetScore], int]:
    """Best next targets in ``enemy`` for our troops, and how many of our villages had troops."""
    tribes = profile.own_tribes if profile else []
    if not tribes:
        msg = "Im Profil fehlt der eigene Stamm (own_tribes) - erst das Profil einrichten."
        raise ValueError(msg)
    own = own_villages(store, tribes)
    if not own:
        msg = "Keine eingelesenen Truppen des eigenen Stamms - erst Truppen sammeln."
        raise ValueError(msg)
    ranked = strategy.rank_targets(
        store.world_config(),
        strategy_candidates(store, enemy),
        own,
        max_seconds=int(max_hours * 3600),
        off_min_pop=profile.off_min_pop if profile else 3000,
        deff_min_pop=deff_min_pop,
        limit=limit,
    )
    return ranked, len(own)


_MANUAL_TYPES = {
    "attack": CommandType.ATTACK,
    "noble": CommandType.CONQUEST,
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
            if send <= datetime.now(zone) and not m.running:
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
                    # "manual:running" = already on its way (no send time to check)
                    origin="manual:running" if m.running else "manual:",
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
        c.model_copy(update={"origin": "kept:" + c.origin.removesuffix(":")})
        for c in manual
        if c.source_id in own_ids
    ]  # "kept:manual" or "kept:manual:running"
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
        ratio_protected=ratio_protected_players(
            store,
            world,
            load_profile(path.parent.parent.parent),
            {s.player for s in sources} | {t.owner for t in targets},
            now or datetime.now(ZoneInfo(settings.timezone)),
        ),
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
    # Everything our players send (new + kept), e.g. for one overview plan in DS Ultimate.
    total.write_text(to_workbench(player_commands(plan)), encoding="utf-8")
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
    write_returns(store, op, plan, path, settings.timezone)
    return OperationOutput(folder, plan, review, total, player_files, target_files)


# --- return times ------------------------------------------------------------------


def plan_fingerprint(plan: Plan) -> str:
    """Hash of everything that ends up in the DS Ultimate plans (changes when re-planned)."""
    cmds = [c.model_dump(mode="json") for c in player_commands(plan)]
    wing = [c.model_dump(mode="json") for c in plan.existing if c.origin.startswith("dsu:")]
    blob = json.dumps([cmds, wing], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def plan_coords(store: WorldStore, plan: Plan) -> dict[int, str]:
    """Village id -> "x|y" for every source and target of the plan."""
    coords: dict[int, str] = {}
    for c in [*plan.commands, *plan.existing]:
        for vid in (c.source_id, c.target_id):
            if vid not in coords and (v := store.village(vid)) is not None:
                coords[vid] = str(v.coord)
    return coords


def write_returns(store: WorldStore, op: Operation, plan: Plan, path: Path, tz: str) -> Path:
    """rueckkehr.md + rueckkehr.json next to the operation (written on every solve)."""
    trips = plan_returns(store.world_config(), plan, fakes=False)
    coords = plan_coords(store, plan)
    out = path.parent / "rueckkehr.md"
    out.write_text(returns_markdown(op, trips, coords, tz), encoding="utf-8")
    (path.parent / "rueckkehr.json").write_text(returns_json(trips, coords), encoding="utf-8")
    return out


def upcoming_returns(
    store: WorldStore, ops_dir: Path, now: datetime
) -> list[tuple[str, ReturnTrip]]:
    """Returns still to come from all published operations of the world, by return time."""
    world = store.world_config()
    rows: list[tuple[str, ReturnTrip]] = []
    for path in sorted(ops_dir.glob("*/operation.yaml")):
        if not (path.parent / "plan.json").exists():
            continue
        try:
            op = load_operation(path)
            if not is_published(op):
                continue
            plan = load_plan(path)
        except (ValueError, OSError):
            continue
        rows += [
            (op.name, t) for t in plan_returns(world, plan, fakes=False) if t.back and t.back >= now
        ]
    return sorted(rows, key=lambda r: (r[1].back, r[1].cmd.send))


def train_waves(
    store: WorldStore, plan: Plan, target: Coord, tz: str
) -> tuple[list[Wave], list[str]]:
    """Everything that lands on ``target`` (ours + wing), as battle waves in landing order."""
    world = store.world_config()
    village = store.village_at(target)
    if village is None:
        msg = f"Ziel {target} existiert nicht auf der Karte."
        raise LookupError(msg)
    owner = store.player(village.player_id) if village.player_id else None
    cmds = [*player_commands(plan), *(c for c in plan.existing if is_wing(c))]
    cmds = sorted((c for c in cmds if c.target_id == village.id), key=lambda c: (c.arrival, c.send))
    waves: list[Wave] = []
    notes: list[str] = []
    for c in cmds:
        if c.type in (
            CommandType.SUPPORT,
            CommandType.STAND_SUPPORT,
            CommandType.FAST_SUPPORT,
            CommandType.FAKE_SUPPORT,
        ):
            continue
        who = c.note.split(" -> ")[0]
        if not c.units:
            notes.append(
                f"{kind_label(c)} von {who}: keine Truppen bekannt (Wing-Plan) - ignoriert."
            )
            continue
        src = store.village(c.source_id)
        attacker = store.player(src.player_id) if src and src.player_id else None
        pct = morale_pct(world, attacker.points if attacker else 0, owner.points if owner else 0)
        waves.append(
            Wave(
                label=f"{c.arrival.astimezone(ZoneInfo(tz)):%H:%M:%S} {kind_label(c)} {who}",
                units=dict(c.units),
                is_noble=c.type == CommandType.CONQUEST,
                night=in_night_bonus(world.night, c.arrival, tz),
                morale=pct / 100,
            )
        )
    return waves, notes


def is_published(op: Operation) -> bool:
    """Approved, or the players already got their plans."""
    return op.status == Status.APPROVED or any(x.kind == "player" for x in op.dsu_links)


def _check_returns(report: CheckReport, store: WorldStore, path: Path, plan: Plan, tz: str) -> None:
    """Our villages must not be planned again while their troops are still away elsewhere."""
    zone = ZoneInfo(tz)
    world = store.world_config()
    mine = player_commands(plan)
    ids = {c.source_id for c in mine}
    away: dict[int, list[tuple[datetime, datetime, str, str]]] = {}
    for other in sorted(path.parent.parent.glob("*/operation.yaml")):
        if other.resolve() == path.resolve() or not (other.parent / "plan.json").exists():
            continue
        try:
            other_op = load_operation(other)
            if not is_published(other_op):
                continue
            other_plan = load_plan(other)
        except (ValueError, OSError):
            continue
        for t in plan_returns(world, other_plan):
            if t.back is not None and t.cmd.source_id in ids and not is_wing(t.cmd):
                away.setdefault(t.cmd.source_id, []).append(
                    (t.cmd.send, t.back, other_op.name, kind_label(t.cmd))
                )
    # Troops that had already left when the troops were imported are not in the import.
    captured = {
        vt.village_id: datetime.fromisoformat(at)
        for vt, _src, at in store.troops()
        if vt.village_id is not None
    }
    hits = 0
    for c in mine:
        for start, end, name, what in away.get(c.source_id, []):
            imported = captured.get(c.source_id)
            if imported is not None and start <= imported:
                continue
            if start <= c.send < end:
                hits += 1
                v = store.village(c.source_id)
                back = f"zurück {end.astimezone(zone):%d.%m. %H:%M:%S}"
                report.warnings.append(
                    f"{v.coord if v else c.source_id} ({c.note.split(' -> ')[0]}): "
                    f"{kind_label(c)} um {c.send.astimezone(zone):%d.%m. %H:%M:%S}, aber die "
                    f"Truppen sind noch für „{name}“ unterwegs ({what}, {back}) und stecken noch "
                    "im Truppen-Import."
                )
    if away and not hits:
        report.ok.append(
            "Kein Dorf ist zur Abschickzeit noch in einer anderen Operation unterwegs."
        )


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
        # manual/moved attacks are not in the existing plan yet, so they are imported too
        cmds = [*moved, *new]
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


@dataclass(frozen=True)
class DsuPublishResult:
    group: DsuGroup
    action: str  # "angelegt", "aktualisiert", "ergänzt"
    info: DsuPlanInfo | None
    problems: list[str]


def publish_dsu_group(
    web: DsuWebClient,
    reader: DsuClient,
    op: Operation,
    group: DsuGroup,
    *,
    update: bool = False,
    api: DsuApiClient | None = None,
) -> tuple[Operation, DsuPublishResult]:
    """Create (or refill) the DS Ultimate plan of one group automatically and verify it.

    - Wing plan (``existing_plan``): our attacks are added, nothing is removed.
    - ``update`` and a saved edit link: the plan is cleared and refilled (link stays).
    - Otherwise a new plan is created.
    With ``api`` (DS Ultimate API key) the official API is used, otherwise the web calls.
    Own plans are always saved (even with problems) so a rerun with ``update`` can repair
    them instead of leaving orphaned plans; wing plans only when the check is clean.
    """
    if group.existing_plan:
        before = reader.inspect(group.existing_plan)
        if api is not None:
            api.add(EditablePlan.from_link(group.existing_plan), group.commands)
        else:
            web.import_workbench(EditablePlan.from_link(group.existing_plan), group.workbench)
        after = reader.inspect(group.existing_plan)
        problems = check_dsu_plan(op, group, after, baseline=before.item_count)
        if not problems:
            op = add_dsu_link(op, group, after)
        return op, DsuPublishResult(group, "ergänzt", after, problems)

    saved = op.dsu_link(group.kind, group.key)
    refill = update and saved is not None and saved.edit_link is not None
    if api is not None and refill:
        assert saved is not None
        assert saved.edit_link is not None
        target = EditablePlan.from_link(saved.edit_link)
        api.clear(target)
        api.add(target, group.commands)
        if saved.title != group.title:  # the API cannot rename: the web call can
            web.set_title(EditablePlan.from_link(saved.edit_link), group.title)
        edit_link, action = saved.edit_link, "aktualisiert"
    elif api is not None:
        edit_link = api.create(op.world, group.title, group.commands).edit_link
        assert edit_link is not None
        action = "angelegt"
    else:
        if refill:
            assert saved is not None
            assert saved.edit_link is not None
            plan = EditablePlan.from_link(saved.edit_link)
            web.clear(plan)
            action = "aktualisiert"
        else:
            plan = web.create(op.world)
            action = "angelegt"
        web.set_title(plan, group.title)
        web.import_workbench(plan, group.workbench)
        edit_link = plan.edit_link
    info = reader.inspect(edit_link)
    problems = check_dsu_plan(op, group, info)
    op = add_dsu_link(op, group, info)
    return op, DsuPublishResult(group, action, info, problems)


@dataclass(frozen=True)
class PlayerProgress:
    """How far one player is, from the "verschickt" ticks in DS Ultimate."""

    player: str
    total: int
    sent: int
    overdue: list[PlannedCommand]  # send time is over, not ticked
    upcoming: list[PlannedCommand]  # not ticked yet, still to send (by send time)


def _item_key(source: int, target: int, arrival: datetime) -> tuple[int, int, int]:
    return source, target, int(arrival.timestamp())


def dsu_progress(
    api: DsuApiClient, op: Operation, plan: Plan, now: datetime
) -> tuple[list[PlayerProgress], list[str]]:
    """Ticked commands per player (needs the API key). Player plans first, else target plans.

    Returns the progress and notes (plans that could not be read). Commands that were
    already running when planned are not counted.
    """
    links = [x for x in op.dsu_links if x.kind == "player"] or [
        x for x in op.dsu_links if x.kind == "target"
    ]
    notes: list[str] = []
    if not links:
        notes.append("Noch keine DS-Ultimate-Pläne angelegt.")
    ticked: set[tuple[int, int, int]] = set()
    for link in links:
        try:
            _, items = api.fetch(link.edit_link or link.show_link)
        except (DsuApiError, DsuLinkError, httpx.HTTPError) as err:
            notes.append(f"{link.key}: {err}")
            continue
        ticked |= {_item_key(i.source_id, i.target_id, i.arrival) for i in items if i.sent}
    out: list[PlayerProgress] = []
    for player, cmds in group_by_player(plan).items():
        todo = [c for c in cmds if not c.origin.endswith("manual:running")]
        open_ = [c for c in todo if _item_key(c.source_id, c.target_id, c.arrival) not in ticked]
        out.append(
            PlayerProgress(
                player,
                total=len(todo),
                sent=len(todo) - len(open_),
                overdue=[c for c in open_ if c.send <= now],
                upcoming=[c for c in open_ if c.send > now],
            )
        )
    return out, notes


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
    now = datetime.now(ZoneInfo(settings.timezone))
    profile = load_profile(path.parent.parent.parent)
    points = _owner_points(store, plan)
    report = run_checks(
        op,
        plan,
        world,
        sources,
        coords,
        now=now,
        tz=settings.timezone,
        points=points,
        ratio_protected=ratio_protected_players(
            store, world, profile, {name for name, _ in points.values()}, now
        ),
    )
    if plan_is_outdated(path):
        report.warnings.insert(0, "operation.yaml ist neuer als der Plan - erst `ap op solve`.")
    if world.newbie_ratio > 0 and (profile is None or profile.world_start is None):
        report.warnings.append(
            f"Weltstart fehlt im Profil (`world_start`) - der {world.newbie_ratio:g}:1-Schutz "
            "gilt deshalb für alle Spieler, die schon vor unserer ersten Sync da waren. "
            "Datum eintragen, damit nicht unnötig Offs gesperrt werden."
        )
    _check_against_profile(report, op, profile)
    _check_returns(report, store, path, plan, settings.timezone)
    if with_dsu:
        _check_dsu_sync(report, store, op, plan)
    return report


def player_joined(store: WorldStore, profile: Profile | None, name: str) -> date | None:
    """Best known join date of an account (the game does not publish it).

    1. hand-entered in the profile (``player_joined``)
    2. first map sync that listed the player - if that was after our first sync
    3. otherwise the world start (``world_start`` in the profile), None if unknown
    """
    if profile is not None:
        for known, day in profile.player_joined.items():
            if known.lower() == name.lower():
                return day
    player = store.player_by_name(name)
    first = store.player_first_seen(player.id) if player else None
    since = store.tracking_since()
    if first is not None and since is not None and first.date() > since.date():
        return first.date()
    return profile.world_start if profile else None


def ratio_protected_players(
    store: WorldStore,
    world: WorldConfig,
    profile: Profile | None,
    names: Iterable[str],
    now: datetime,
) -> frozenset[str]:
    """Players still under the point-ratio protection (10:1 rule, counted per account)."""
    return frozenset(
        n
        for n in names
        if n not in ("Barbar", "?")
        and ratio_protected(world, player_joined(store, profile, n), now)
    )


def _owner_points(store: WorldStore, plan: Plan) -> dict[int, tuple[str, int]]:
    """Village id -> (owner name, owner points) for every source and target of the plan."""
    out: dict[int, tuple[str, int]] = {}
    for c in [*plan.commands, *plan.existing]:
        for vid in (c.source_id, c.target_id):
            if vid in out:
                continue
            village = store.village(vid)
            player = store.player(village.player_id) if village and village.player_id else None
            out[vid] = (player.name, player.points) if player else ("Barbar", 0)
    return out


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


# --- Google Doc ---------------------------------------------------------------

GDOC_ID_RE = re.compile(r"(?:/d/)?([A-Za-z0-9_-]{25,})")


def doc_path(op_path: Path) -> Path:
    return op_path.parent / "doc.html"


def build_operation_doc(store: WorldStore, op: Operation, plan: Plan, tz: str) -> str:
    """HTML of the operation document (Google Docs converts it into a normal Doc)."""
    millis = store.world_config().millis_arrival
    coords = plan_coords(store, plan)
    return gdoc.operation_doc(op, plan, target_infos(store, op), coords, tz, millis=millis)


def build_doc_update(
    store: WorldStore, op: Operation, plan: Plan, tz: str, end_index: int
) -> list[dict[str, Any]]:
    """batchUpdate requests that rewrite the existing Google Doc in place (same link)."""
    millis = store.world_config().millis_arrival
    coords = plan_coords(store, plan)
    blocks = gdoc.operation_blocks(op, plan, target_infos(store, op), coords, tz, millis=millis)
    return rewrite_requests(blocks, end_index)


def parse_gdoc_id(ref: str) -> str:
    """Doc id from an id or a docs.google.com link."""
    m = GDOC_ID_RE.search(ref.strip())
    if m is None:
        msg = f"Keine Google-Doc-ID erkannt: {ref!r}"
        raise ValueError(msg)
    return m.group(1)


def gdoc_link(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def gdoc_view_link(doc_id: str) -> str:
    """Link for readers (the doc is shared as "anyone with the link can view")."""
    return f"https://docs.google.com/document/d/{doc_id}/view"


_FIXED_NOW = datetime(2000, 1, 1, tzinfo=UTC)


def doc_fingerprint(store: WorldStore, op: Operation, plan: Plan, tz: str) -> str:
    """Hash of the doc content without the "Stand" time: changes exactly when the doc would."""
    millis = store.world_config().millis_arrival
    coords = plan_coords(store, plan)
    blocks = gdoc.operation_blocks(
        op, plan, target_infos(store, op), coords, tz, millis=millis, now=_FIXED_NOW
    )
    return hashlib.sha256(repr(blocks).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class GdocState:
    """Where the Google Doc of an operation stands compared to the latest plan."""

    status: str  # "fehlt" (no doc yet) | "veraltet" (plan changed) | "aktuell"
    geteilt: bool  # shared as "anyone with the link can view"
    fingerprint: str
    view_link: str | None

    @property
    def ready(self) -> bool:
        return self.status == "aktuell" and self.geteilt


def gdoc_state(store: WorldStore, op: Operation, plan: Plan, tz: str) -> GdocState:
    fp = doc_fingerprint(store, op, plan, tz)
    if not op.gdoc_id:
        status = "fehlt"
    elif op.gdoc_stand != fp:
        status = "veraltet"
    else:
        status = "aktuell"
    link = gdoc_view_link(op.gdoc_id) if op.gdoc_id else None
    return GdocState(status, op.gdoc_geteilt, fp, link)


def mark_gdoc(
    store: WorldStore,
    path: Path,
    tz: str,
    *,
    doc_id: str | None = None,
    geteilt: bool | None = None,
) -> Operation:
    """Remember the doc (id), that it now shows the current plan, and whether it is shared.

    A new id resets the sharing flag (a fresh doc is private until shared)."""
    op = load_operation(path)
    update: dict[str, Any] = {"gdoc_stand": doc_fingerprint(store, op, load_plan(path), tz)}
    if doc_id is not None and doc_id != op.gdoc_id:
        update |= {"gdoc_id": doc_id, "gdoc_geteilt": False}
    if geteilt is not None:
        update["gdoc_geteilt"] = geteilt
    op = op.model_copy(update=update)
    save_operation(op, path)
    return op
