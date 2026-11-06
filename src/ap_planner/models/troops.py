"""Troop data imported from user-provided exports (never fetched automatically)."""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ap_planner.models.map import Coord
from ap_planner.models.world import Unit


class VillageTroops(BaseModel):
    model_config = ConfigDict(frozen=True)

    coord: Coord
    name: str
    village_id: int | None = None
    units: dict[Unit, int] = Field(default_factory=dict)
    outgoing: int = 0  # commands currently leaving this village
    incoming: int = 0  # attacks currently incoming on this village
    # Numeric columns we could not map to a unit (kept for debugging/mapping).
    extra: list[int] = Field(default_factory=list)


class TroopSnapshot(BaseModel):
    source: str  # e.g. "overview_paste", "saved_html", "<script name>"
    captured_at: AwareDatetime
    villages: list[VillageTroops]
