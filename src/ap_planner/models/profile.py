"""Player / tribe profile: personal defaults and strategy preferences per world.

Stored in ``data/<world>/profil.yaml`` (not in git). Every new operation starts from
these values; an ``operation.yaml`` can still override each of them.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ap_planner.models.operation import SendWindow
from ap_planner.models.world import Unit


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: object) -> object:
        if isinstance(data, dict):  # removed option (fusion offs)
            return {k: v for k, v in data.items() if k != "fusion_min_pop"}
        return data

    world: str
    server: str = "die-staemme.de"
    timezone: str = "Europe/Berlin"
    # Start date of the world (for the 10:1 point-ratio protection; unknown = still active).
    world_start: date | None = None
    # Known join dates of single accounts (10:1 rule counts per account), e.g. {"Name": 2026-11-01}.
    player_joined: dict[str, date] = Field(default_factory=dict)
    player: str = ""  # who plans (for the agent's context)
    # Our tribe(s) - their villages send the planned attacks ("Main").
    own_tribes: list[str] = Field(default_factory=list)
    # Allied tribes (e.g. the wing) - their DS-Ultimate plans are read, never planned.
    allied_tribes: list[str] = Field(default_factory=list)

    # Defaults for every operation
    send_window: SendWindow = Field(default_factory=SendWindow)
    off_min_pop: int = 3000
    noble_escort: dict[Unit, int] = Field(default_factory=lambda: {Unit.AXE: 100})
    fake_unit: Unit = Unit.RAM
    home_guard: dict[Unit, int] = Field(default_factory=dict)
    off_send_gap_s: int = 2
    allow_second_break: bool = True
    max_troop_age_hours: int = 24

    # Free-text strategy preferences the planning agent must respect,
    # e.g. "Fakes nie aus Dörfern mit eingehenden Angriffen".
    preferences: list[str] = Field(default_factory=list)

    def operation_defaults(self) -> dict[str, Any]:
        """Values an operation inherits when its YAML does not set them."""
        return {
            "world": self.world,
            "send_window": self.send_window.model_dump(mode="json"),
            "off_send_gap_s": self.off_send_gap_s,
            "allow_second_break": self.allow_second_break,
            "max_troop_age_hours": self.max_troop_age_hours,
            "home_guard": {u.value: n for u, n in self.home_guard.items()},
            "participants": {"allies": list(self.own_tribes)},
            "off_settings": {"min_pop": self.off_min_pop},
            "noble_settings": {"escort": {u.value: n for u, n in self.noble_escort.items()}},
            "fake_settings": {"unit": self.fake_unit.value},
        }


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """``override`` wins; nested dicts are merged key by key."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
