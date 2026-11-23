"""Battle simulation (approximation of the Die Stämme battle formula) and train blocking.

Formula (as in the common DS simulators):
- Attack strength per type (infantry / cavalry / archer) = units x attack value, times morale
  and (1 + luck). Spies do not fight.
- Defense against each type = units x defense value for that type; the attacker's type mix
  weights it. Wall: unit defense x 1.037^level plus a base defense of 20 + 50 x level.
  Night bonus multiplies the whole defense (world setting, usually x2).
- Stronger side wins. Loser: everything dies. Winner loses the share (weaker/stronger)^1.5
  of every unit.

Not modelled: rams/catapults lowering the wall during the fight (pass the wall level that
remains for the AGs separately), paladin items, church, watchtower, flags, research levels.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from ap_planner.models.world import Unit, WorldConfig

CAVALRY = frozenset({Unit.LIGHT, Unit.HEAVY, Unit.KNIGHT})
ARCHERS = frozenset({Unit.ARCHER, Unit.MARCHER})
NOT_FIGHTING = frozenset({Unit.SPY})
WALL_BONUS = 1.037
LOSS_EXPONENT = 1.5


def _kind(u: Unit) -> str:
    if u in CAVALRY:
        return "cav"
    if u in ARCHERS:
        return "arch"
    return "inf"


@dataclass(frozen=True)
class FightResult:
    attacker_won: bool
    attacker_left: dict[Unit, int]
    defender_left: dict[Unit, int]
    attack: float
    defense: float


def attack_strength(
    world: WorldConfig, units: Mapping[Unit, int], *, morale: float = 1.0, luck: float = 0.0
) -> dict[str, float]:
    out = {"inf": 0.0, "cav": 0.0, "arch": 0.0}
    for u, n in units.items():
        if n > 0 and u in world.units and u not in NOT_FIGHTING:
            out[_kind(u)] += n * world.units[u].attack
    factor = morale * (1 + luck)
    return {k: v * factor for k, v in out.items()}


def defense_strength(
    world: WorldConfig,
    units: Mapping[Unit, int],
    attack_mix: Mapping[str, float],
    *,
    wall: int = 0,
    night: bool = False,
) -> float:
    total = sum(attack_mix.values())
    if total <= 0:
        return 0.0
    against = {"inf": 0.0, "cav": 0.0, "arch": 0.0}
    for u, n in units.items():
        if n <= 0 or u not in world.units:
            continue
        info = world.units[u]
        against["inf"] += n * info.defense
        against["cav"] += n * info.defense_cavalry
        against["arch"] += n * info.defense_archer
    weighted = sum(against[k] * attack_mix[k] / total for k in against)
    value = weighted * WALL_BONUS**wall + 20 + 50 * wall
    return value * (world.night.def_factor if night else 1.0)


def _survivors(units: Mapping[Unit, int], loss: float) -> dict[Unit, int]:
    return {u: round(n * (1 - loss)) for u, n in units.items() if n > 0}


def fight(
    world: WorldConfig,
    attacker: Mapping[Unit, int],
    defender: Mapping[Unit, int],
    *,
    wall: int = 0,
    night: bool = False,
    morale: float = 1.0,
    luck: float = 0.0,
) -> FightResult:
    mix = attack_strength(world, attacker, morale=morale, luck=luck)
    a = sum(mix.values())
    d = defense_strength(world, defender, mix, wall=wall, night=night)
    if a > d:
        loss = (d / a) ** LOSS_EXPONENT if a else 1.0
        return FightResult(True, _survivors(attacker, loss), {}, a, d)
    loss = (a / d) ** LOSS_EXPONENT if d else 0.0
    return FightResult(False, {}, _survivors(defender, loss), a, d)


@dataclass(frozen=True)
class Wave:
    """One command of the train, in landing order."""

    label: str  # e.g. "Off Bobby"
    units: dict[Unit, int]
    is_noble: bool
    night: bool
    morale: float = 1.0


@dataclass
class TrainResult:
    ags_through: int
    ags_total: int
    rows: list[tuple[str, bool, int]] = field(default_factory=list)  # label, won, deff pop left


def run_train(
    world: WorldConfig,
    waves: list[Wave],
    defender: Mapping[Unit, int],
    *,
    wall: int,
    wall_ags: int,
    luck: float = 0.0,
) -> TrainResult:
    """Fight all waves one after the other; the deff that survives meets the next wave."""
    deff = dict(defender)
    res = TrainResult(0, sum(1 for w in waves if w.is_noble))
    for w in waves:
        r = fight(
            world,
            w.units,
            deff,
            wall=wall_ags if w.is_noble else wall,
            night=w.night,
            morale=w.morale,
            luck=luck,
        )
        deff = r.defender_left
        if w.is_noble and r.attacker_won:
            res.ags_through += 1
        pop = sum(n * world.units[u].pop for u, n in deff.items() if u in world.units)
        res.rows.append((w.label, r.attacker_won, pop))
    return res


# Loyalty: every successful AG lowers it by 20-35 (random); the village falls at <= 0.
LOYALTY_MAX_DROP = 35
LOYALTY_AVG_DROP = 27.5


def blocked(ags_through: int, *, sure: bool = True) -> bool:
    """Is the conquest stopped? ``sure``: even with the best loyalty drops for the attacker."""
    drop = LOYALTY_MAX_DROP if sure else LOYALTY_AVG_DROP
    return ags_through * drop < 100


def scale(package: Mapping[Unit, int], k: float) -> dict[Unit, int]:
    return {u: round(n * k) for u, n in package.items()}


def deff_needed(
    world: WorldConfig,
    waves: list[Wave],
    package: Mapping[Unit, int],
    *,
    wall: int,
    wall_ags: int,
    luck: float = 0.0,
    sure: bool = True,
    max_packages: float = 500.0,
) -> float | None:
    """Smallest number of deff packages (0.01 steps) that blocks the train; None = > max."""

    def ok(k: float) -> bool:
        res = run_train(world, waves, scale(package, k), wall=wall, wall_ags=wall_ags, luck=luck)
        return blocked(res.ags_through, sure=sure)

    if ok(0):
        return 0.0
    if not ok(max_packages):
        return None
    lo, hi = 0, round(max_packages * 100)  # in hundredths of a package
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid / 100):
            hi = mid
        else:
            lo = mid
    return hi / 100
