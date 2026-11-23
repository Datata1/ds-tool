"""Morale (Moral) and the point-ratio attack protection of new worlds.

Morale: a big player attacking a small one fights with reduced strength.
Points-based formula of the game: ``3 * defender / attacker + 0.3``, between 30 % and 100 %.
Worlds with a time-based component (``moral`` = 2/3) can only be *higher* than this, so the
points-based value is the safe (pessimistic) estimate. Barbarian villages: always 100 %.

Point-ratio protection (``newbie/ratio`` + ``newbie/ratio_days``): during an account's first
``ratio_days`` days on the world, it cannot attack or be attacked by players with more than
``ratio`` times (or less than 1/ratio) its points (e.g. 10:1). Supports are not affected.
The join date of an account is not public: the caller estimates it (see
``services.ratio_protected_players``).
"""

import math
from datetime import date, datetime, timedelta

from ap_planner.models.world import WorldConfig

MORALE_MIN_PCT = 30


def morale_pct(world: WorldConfig, attacker_points: int, defender_points: int) -> int:
    """Morale of the attacker in percent (100 = full strength)."""
    if world.moral == 0 or attacker_points <= 0 or defender_points <= 0:
        return 100  # morale off, barbarian target or unknown points
    value = 3 * defender_points / attacker_points + 0.3
    return max(MORALE_MIN_PCT, min(100, math.floor(value * 100)))


def ratio_protected(world: WorldConfig, joined: date | None, now: datetime) -> bool:
    """Is an account that joined on ``joined`` still under the point-ratio protection?

    Unknown join date = assume yes (the safe side: no impossible attacks get planned).
    """
    if world.newbie_ratio <= 0 or world.newbie_ratio_days <= 0:
        return False
    if joined is None:
        return True
    return now.date() < joined + timedelta(days=world.newbie_ratio_days)


def point_ratio(attacker_points: int, defender_points: int) -> float:
    """Bigger points divided by smaller points (1.0 if one side is unknown/barbarian)."""
    if attacker_points <= 0 or defender_points <= 0:
        return 1.0
    return max(attacker_points, defender_points) / min(attacker_points, defender_points)


def attack_blocked(
    world: WorldConfig, attacker_points: int, defender_points: int, *, active: bool
) -> bool:
    """True if the game refuses this attack because of the point ratio."""
    return active and point_ratio(attacker_points, defender_points) > world.newbie_ratio
