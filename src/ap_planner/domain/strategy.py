"""Strategy: which enemy villages are good next targets for the troops we have?

Pure functions over public map data and imported troops (no game pages). For every
candidate village we look at:

- **AG-Laufzeit:** fastest noble from one of our villages that has nobles (within the world's
  maximum noble distance).
- **Offs in Reichweite:** full offs (by offensive population) that reach the target in at most
  the given time (ram speed).
- **Readel-Vorteil:** after we conquer the village, the enemy tries to take it back. We can
  hold it if our defence arrives before their noble: ``enemy noble time - our deff time``.
  Positive = our support is there first. Enemy nobles may come from any village of the
  target's tribe (we do not know where their nobles are, so we assume every village has one).
- **Gegner-Dichte:** enemy villages around the target (pressure after the conquest).
- **Moral:** attacker strength against the owner (points-based, pessimistic).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from ap_planner.domain import travel
from ap_planner.domain.morale import morale_pct
from ap_planner.models.map import Village
from ap_planner.models.world import Unit, WorldConfig

OFF_UNITS: dict[Unit, int] = {
    Unit.AXE: 1,
    Unit.LIGHT: 4,
    Unit.MARCHER: 5,
    Unit.RAM: 5,
    Unit.CATAPULT: 8,
}
DEFF_UNITS = (Unit.SPEAR, Unit.SWORD, Unit.ARCHER, Unit.HEAVY)
DENSITY_RADIUS = 10.0


@dataclass(frozen=True)
class OwnVillage:
    village: Village
    player: str
    points: int  # player points (for morale)
    units: dict[Unit, int]

    def off_pop(self) -> int:
        return sum(self.units.get(u, 0) * pop for u, pop in OFF_UNITS.items())

    def deff_pop(self, world: WorldConfig) -> int:
        return sum(
            self.units.get(u, 0) * world.units[u].pop for u in DEFF_UNITS if u in world.units
        )

    def deff_speed(self, world: WorldConfig) -> float | None:
        """Minutes per field of the slowest defensive unit present (None = no deff)."""
        present = [u for u in DEFF_UNITS if self.units.get(u, 0) > 0 and u in world.units]
        return max((world.unit_speed_min(u) for u in present), default=None)


@dataclass(frozen=True)
class Candidate:
    village: Village
    owner: str
    tribe: str
    owner_points: int
    # villages of the target's side that could send a noble back (owner + his tribe)
    enemy_villages: Sequence[Village]


@dataclass(frozen=True)
class Reach:
    coord: str
    player: str  # "" = not known (enemy villages)
    seconds: int


@dataclass(frozen=True)
class TargetScore:
    village: Village
    owner: str
    tribe: str
    ag: Reach | None  # fastest own noble
    nobles_in_range: int  # nobles that arrive within max time
    offs_in_range: int  # full offs that arrive within max time
    deff: Reach | None  # fastest own defence (min deff population)
    enemy_ag: Reach | None  # fastest possible enemy noble back
    density: int  # enemy villages within DENSITY_RADIUS
    morale: int
    score: float

    @property
    def readel_margin_s(self) -> int | None:
        """Enemy noble time minus our deff time (positive = we hold it)."""
        if self.enemy_ag is None or self.deff is None:
            return None
        return self.enemy_ag.seconds - self.deff.seconds


def _secs(world: WorldConfig, a: Village, b: Village, minutes_per_field: float) -> int:
    return travel.travel_seconds(travel.distance(a.coord, b.coord), minutes_per_field)


def score_target(
    world: WorldConfig,
    cand: Candidate,
    own: Sequence[OwnVillage],
    *,
    max_seconds: int,
    off_min_pop: int,
    deff_min_pop: int,
) -> TargetScore:
    t = cand.village
    snob_speed = world.unit_speed_min(Unit.SNOB)
    ram_speed = world.unit_speed_min(Unit.RAM)
    ag: Reach | None = None
    nobles = offs = 0
    deff: Reach | None = None
    attacker_points = 0
    for o in own:
        dist = travel.distance(o.village.coord, t.coord)
        snobs = o.units.get(Unit.SNOB, 0)
        if snobs and dist <= world.snob_max_dist:
            secs = travel.travel_seconds(dist, snob_speed)
            if ag is None or secs < ag.seconds:
                ag = Reach(str(o.village.coord), o.player, secs)
                attacker_points = o.points
            if secs <= max_seconds:
                nobles += snobs
        if o.off_pop() >= off_min_pop and travel.travel_seconds(dist, ram_speed) <= max_seconds:
            offs += 1
        speed = o.deff_speed(world)
        if speed is not None and o.deff_pop(world) >= deff_min_pop:
            secs = travel.travel_seconds(dist, speed)
            if deff is None or secs < deff.seconds:
                deff = Reach(str(o.village.coord), o.player, secs)
    enemy_ag: Reach | None = None
    density = 0
    for e in cand.enemy_villages:
        if e.id == t.id:
            continue
        dist = travel.distance(e.coord, t.coord)
        if dist <= DENSITY_RADIUS:
            density += 1
        if dist <= world.snob_max_dist:
            secs = travel.travel_seconds(dist, snob_speed)
            if enemy_ag is None or secs < enemy_ag.seconds:
                enemy_ag = Reach(str(e.coord), "", secs)  # owner unknown here: coord only
    morale = morale_pct(world, attacker_points, cand.owner_points) if cand.owner_points else 100
    result = TargetScore(t, cand.owner, cand.tribe, ag, nobles, offs, deff, enemy_ag, density,
                         morale, 0.0)  # fmt: skip
    return _with_score(result, max_seconds)


def _with_score(s: TargetScore, max_seconds: int) -> TargetScore:
    """Higher = better. Hours as unit; every part is clipped so no single one dominates."""
    if s.ag is None or s.ag.seconds > max_seconds:
        return replace(s, score=-1e9)
    hours = 3600.0
    margin = s.readel_margin_s
    readel = 6.0 if margin is None else max(-12.0, min(12.0, margin / hours))
    value = (
        2.0 * readel
        + min(s.offs_in_range, 10)
        + min(s.nobles_in_range, 8) * 0.5
        - s.ag.seconds / hours
        - 0.3 * min(s.density, 20)
        + (s.morale - 100) / 10
    )
    return replace(s, score=round(value, 2))


def rank_targets(
    world: WorldConfig,
    candidates: Iterable[Candidate],
    own: Sequence[OwnVillage],
    *,
    max_seconds: int,
    off_min_pop: int,
    deff_min_pop: int,
    limit: int = 15,
) -> list[TargetScore]:
    """Best targets first; villages our nobles cannot reach in time are left out."""
    scored = [
        score_target(
            world, c, own, max_seconds=max_seconds, off_min_pop=off_min_pop,
            deff_min_pop=deff_min_pop,
        )
        for c in candidates
    ]  # fmt: skip
    reachable = [s for s in scored if s.ag is not None and s.ag.seconds <= max_seconds]
    return sorted(reachable, key=lambda s: (-s.score, s.ag.seconds if s.ag else 0))[:limit]
