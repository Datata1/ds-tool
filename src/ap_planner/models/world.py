"""World-level settings as published by ``interface.php``."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Unit(StrEnum):
    """Unit identifiers as used by the game and by DS Ultimate / Workbench."""

    SPEAR = "spear"
    SWORD = "sword"
    AXE = "axe"
    ARCHER = "archer"
    SPY = "spy"
    LIGHT = "light"
    MARCHER = "marcher"
    HEAVY = "heavy"
    RAM = "ram"
    CATAPULT = "catapult"
    KNIGHT = "knight"
    SNOB = "snob"
    MILITIA = "militia"


class UnitInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    unit: Unit
    pop: int
    # Minutes per field, already adjusted for world speed and unit speed.
    speed: float
    attack: int
    defense: int
    defense_cavalry: int
    defense_archer: int
    carry: int
    build_time: float


class NightBonus(BaseModel):
    model_config = ConfigDict(frozen=True)

    active: bool
    start_hour: int
    end_hour: int
    def_factor: float = 2.0


class WorldConfig(BaseModel):
    """The subset of ``get_config`` that matters for attack planning."""

    model_config = ConfigDict(frozen=True)

    world: str
    speed: float
    unit_speed: float
    moral: int
    millis_arrival: bool
    attack_gap_ms: int
    knight: bool
    archer: bool
    church: bool
    watchtower: bool
    fake_limit_pct: float
    snob_max_dist: int
    night: NightBonus
    # Point-ratio protection: no attacks between players above ratio:1 in the first days.
    newbie_ratio: float = 0
    newbie_ratio_days: int = 0
    units: dict[Unit, UnitInfo]

    def unit_speed_min(self, unit: Unit) -> float:
        return self.units[unit].speed
