"""Operation spec: the answers from the guided prompt, as a typed document.

Stored as YAML (``data/<world>/ops/<name>/operation.yaml``). The solver reads it,
and later steps (review status, DS Ultimate links) are written back into it.
"""

from datetime import datetime, time
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ap_planner.models.map import Coord
from ap_planner.models.world import Unit

OFF_UNITS: tuple[Unit, ...] = (Unit.AXE, Unit.LIGHT, Unit.MARCHER, Unit.RAM, Unit.CATAPULT)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SendWindow(_Strict):
    """Daily time window (server time) in which players can send. May wrap midnight."""

    start: time = time(7, 0)
    end: time = time(23, 0)

    def contains(self, t: time) -> bool:
        if self.start <= self.end:
            return self.start <= t <= self.end
        return t >= self.start or t <= self.end


class OffDefinition(_Strict):
    """Offs are measured in offensive population (axe 1, light 4, ram 5, ...)."""

    # One "off" = this much offensive population.
    min_pop: int = 3000
    # Smallest village part that may join a fusion off (Fusionsoff).
    fusion_min_pop: int = 1000
    units: list[Unit] = Field(default_factory=lambda: list(OFF_UNITS))
    # Players who must not send offs (their AGs and fakes are still allowed).
    exclude_players: list[str] = Field(default_factory=list)


class NobleSettings(_Strict):
    # Escort per nobleman command (real or fake AG), taken from the sending village.
    escort: dict[Unit, int] = Field(default_factory=lambda: {Unit.AXE: 100})


class FakeSettings(_Strict):
    # The "real" unit that makes a fake look like an attack (ram or catapult).
    unit: Unit = Unit.RAM
    # Units used to fill up to the world's fake limit, in order of preference.
    filler: list[Unit] = Field(
        default_factory=lambda: [Unit.SPEAR, Unit.SWORD, Unit.SPY, Unit.AXE, Unit.LIGHT]
    )
    max_per_village: int = 10


class DsuMode(StrEnum):
    """How an existing DS Ultimate plan (``dsu_plan``) is used for a target."""

    # Import our new attacks into the existing plan (wing + old + new).
    MERGE = "merge"
    # New plan per target: wing attacks from the existing plan + our new attacks
    # (our old attacks in that plan are dropped).
    SPLIT = "split"
    # Existing plan stays exactly as it is; nothing new is planned, troops count as used.
    KEEP = "keep"
    # New plan per target with ALL attacks of the existing plan for this target, unchanged.
    COPY = "copy"


class WingRedirect(_Strict):
    """Take the wing's attacks on another target from a DS Ultimate plan and send them here."""

    dsu_plan: str
    coord: Coord  # the original target in that plan

    @field_validator("coord", mode="before")
    @classmethod
    def _parse_coord(cls, v: object) -> object:
        return Coord.parse(v) if isinstance(v, str) else v


class ManualAttack(_Strict):
    """A single attack set by hand (e.g. from a wing village without troop data)."""

    coord: Coord  # source village
    slowest_unit: Unit = Unit.AXE
    kind: Literal["attack", "noble", "fake", "support"] = "attack"
    units: dict[Unit, int] = Field(default_factory=dict)
    arrival: datetime | None = None  # default: the target's arrival
    # Already on its way (send time in the past): keep it for the ordering rule.
    running: bool = False
    note: str = ""

    @field_validator("coord", mode="before")
    @classmethod
    def _parse_coord(cls, v: object) -> object:
        return Coord.parse(v) if isinstance(v, str) else v


class SupportOrder(_Strict):
    """Flex-deff support that lands right after the last AG (never before it)."""

    # Defensive population to send (spear 1, sword 1, heavy 6, ...).
    min_pop: int = Field(3000, ge=1)
    units: list[Unit] = Field(default_factory=lambda: [Unit.SPEAR, Unit.SWORD, Unit.HEAVY])
    # Share of a village's support units that stays home (0.0 = send everything).
    keep_home_share: float = Field(0.0, ge=0, le=1)
    # Radius (fields) for the enemy re-noble analysis around the target.
    enemy_radius: float = 15.0
    # Fixed landing time (e.g. 23:00:00 to land in the night bonus). Default: right after
    # the last AG (same second if sent later, else +1 s). Never before the last AG.
    arrival: datetime | None = None
    # Use as few villages as possible: biggest deff villages first (instead of earliest).
    few_villages: bool = False


class TargetOrder(_Strict):
    coord: Coord
    # Full offs wanted (in units of off_settings.min_pop).
    offs: int = Field(0, ge=0)
    # Allow combining smaller village offs into one (Fusionsoff).
    fusion: bool = False
    # Real noblemen (AGs) landing here; may come from different villages/players.
    nobles: int = Field(0, ge=0)
    # Who nobles: player names or village coords ("x|y"). Empty = whoever is fastest.
    nobles_from: list[str] = Field(default_factory=list)
    # Tab offs: extra offs landing in the AG second BETWEEN the AGs (sent after the first AG,
    # before the last one) - they clear deff the defender tabs in between the AGs.
    tab_offs: int = Field(0, ge=0)
    tab_min_pop: int = Field(1000, ge=1)
    fakes: int = Field(0, ge=0)
    # Fake AGs: a nobleman + escort as a decoy (uses a real AG!).
    fake_nobles: int = Field(0, ge=0)
    support: SupportOrder | None = None
    # Villages that MUST send their off to this target (e.g. "SeWarri's off goes here").
    off_from: list[Coord] = Field(default_factory=list)
    # Redirect wing attacks from other targets to this one (same villages, new send times).
    wing_from: list[WingRedirect] = Field(default_factory=list)
    # Attacks set by hand; their times are computed, the planner respects them.
    manual_attacks: list[ManualAttack] = Field(default_factory=list)
    arrival: datetime | None = None  # overrides Operation.arrival
    note: str = ""
    # Edit link of an existing DS Ultimate plan (e.g. from the wing) and how to use it.
    dsu_plan: str | None = None
    dsu_mode: DsuMode = DsuMode.MERGE

    @field_validator("coord", mode="before")
    @classmethod
    def _parse_coord(cls, v: object) -> object:
        return Coord.parse(v) if isinstance(v, str) else v

    @field_validator("off_from", mode="before")
    @classmethod
    def _parse_coords(cls, v: object) -> object:
        if isinstance(v, list):
            return [Coord.parse(c) if isinstance(c, str) else c for c in v]
        return v

    @property
    def plans_nothing_new(self) -> bool:
        return self.dsu_plan is not None and self.dsu_mode in (DsuMode.KEEP, DsuMode.COPY)

    @model_validator(mode="after")
    def _something_to_do(self) -> Self:
        if self.dsu_mode != DsuMode.MERGE and self.dsu_plan is None:
            msg = f"Target {self.coord}: dsu_mode {self.dsu_mode.value} needs a dsu_plan link."
            raise ValueError(msg)
        wanted = self.offs + self.nobles + self.fakes + self.fake_nobles
        if self.plans_nothing_new:
            if wanted or self.support:
                msg = f"Target {self.coord}: dsu_mode {self.dsu_mode.value} plans nothing new."
                raise ValueError(msg)
        elif wanted == 0 and self.support is None and not self.manual_attacks:
            msg = f"Target {self.coord}: needs at least one off, noble, fake or support."
            raise ValueError(msg)
        return self


class Participants(_Strict):
    """Who attacks. Empty lists = everyone with imported troops."""

    allies: list[str] = Field(default_factory=list)  # tribe tags
    players: list[str] = Field(default_factory=list)
    exclude_players: list[str] = Field(default_factory=list)
    exclude_villages: list[Coord] = Field(default_factory=list)

    @field_validator("exclude_villages", mode="before")
    @classmethod
    def _parse_coords(cls, v: object) -> object:
        if isinstance(v, list):
            return [Coord.parse(c) if isinstance(c, str) else c for c in v]
        return v


class Status(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"


PlanKind = Literal["target", "player"]


class DsuPlanLink(_Strict):
    """A DS Ultimate attack plan created for one target (SF review) or one player."""

    kind: PlanKind
    key: str  # target coord "x|y" or player name
    title: str = ""
    plan_id: int | None = None
    show_link: str  # the view link - the only one that gets shared
    # Local only (lets you edit the plan later). Never put this into announcements.
    edit_link: str | None = None


# dm = direct message, thread = private thread per player in the "befehle" channel
MessageKind = Literal["review", "spieler", "dm", "thread"]


class SentMessage(_Strict):
    """A Discord message (possibly split into parts) the tool has sent for this operation.

    Kept so a re-run edits the same message instead of posting it twice.
    """

    kind: MessageKind
    key: str  # channel alias ("review", "ankuendigung") or player name (dm, thread)
    channel_id: str
    message_ids: list[str]
    content_hash: str


class Operation(_Strict):
    name: str
    world: str
    # Default arrival (server time, Europe/Berlin), e.g. "2026-11-10 09:00:00".
    arrival: datetime
    send_window: SendWindow = Field(default_factory=SendWindow)
    avoid_night_bonus: bool = True
    # Same-second rule (no ms): commands landing in one second arrive in send order, so
    # every off must be SENT at least this many seconds before the first AG of that second.
    off_send_gap_s: int = Field(2, ge=0)
    # If same second is impossible: offs land 1 s before the AGs ("Sekunde brechen").
    allow_second_break: bool = True
    max_troop_age_hours: int = 24
    # Fake protection: units that always stay home in every village (never planned).
    home_guard: dict[Unit, int] = Field(default_factory=dict)
    participants: Participants = Field(default_factory=Participants)
    off_settings: OffDefinition = Field(default_factory=OffDefinition)
    noble_settings: NobleSettings = Field(default_factory=NobleSettings)
    fake_settings: FakeSettings = Field(default_factory=FakeSettings)
    targets: list[TargetOrder] = Field(min_length=1)

    # Filled in during the workflow.
    status: Status = Status.DRAFT
    review_notes: list[str] = Field(default_factory=list)
    # "Worum geht es?" in the Google Doc (free text, lines starting with "- " = bullets).
    beschreibung: str = ""
    # Google Doc of this operation (file id), set after the first upload.
    gdoc_id: str | None = None
    # Fingerprint of the plan content last written into the Google Doc (None = never written).
    # The doc is the projection of the latest plan: differs from the current one -> rewrite it.
    gdoc_stand: str | None = None
    # True once the doc is shared as "anyone with the link can view".
    gdoc_geteilt: bool = False
    dsu_links: list[DsuPlanLink] = Field(default_factory=list)
    discord_messages: list[SentMessage] = Field(default_factory=list)

    def dsu_link(self, kind: PlanKind, key: str) -> DsuPlanLink | None:
        return next((x for x in self.dsu_links if x.kind == kind and x.key == key), None)

    def sent_message(self, kind: MessageKind, key: str) -> SentMessage | None:
        return next((m for m in self.discord_messages if m.kind == kind and m.key == key), None)

    @model_validator(mode="after")
    def _unique_targets(self) -> Self:
        coords = [t.coord for t in self.targets]
        dupes = {str(c) for c in coords if coords.count(c) > 1}
        if dupes:
            msg = f"Targets listed twice: {', '.join(sorted(dupes))} - merge them."
            raise ValueError(msg)
        return self
