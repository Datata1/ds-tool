"""Solver output: a list of concrete commands."""

from datetime import datetime, timedelta
from enum import IntEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ap_planner.models.world import Unit


class CommandType(IntEnum):
    """Attack-type icon IDs as used by DS Ultimate / DS Workbench."""

    NONE = -1
    ATTACK = 8
    CONQUEST = 11
    FAKE = 14
    WALLBREAKER = 45
    SUPPORT = 0
    STAND_SUPPORT = 1
    FAST_SUPPORT = 7
    FAKE_SUPPORT = 46


class PlannedCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: int
    target_id: int
    source_player_id: int | None = None
    units: dict[Unit, int] = Field(default_factory=dict)
    slowest_unit: Unit
    type: CommandType
    arrival: AwareDatetime
    send: AwareDatetime
    travel: timedelta
    note: str = ""
    # "main" = planned by us; "dsu:<plan id>" = already in an existing DS Ultimate plan (wing)
    origin: str = "main"
    # Special role inside a train: "tab" = off landing between the AGs on purpose (tabbing).
    role: str = ""

    @property
    def is_existing(self) -> bool:
        return self.origin != "main"


class Plan(BaseModel):
    world: str
    name: str
    created_at: datetime
    commands: list[PlannedCommand]
    # Commands that already exist in DS Ultimate plans (e.g. the wing); not exported again.
    existing: list[PlannedCommand] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
