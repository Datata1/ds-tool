"""Private Discord threads per player, DS Ultimate API key, progress and reminders."""

import json
from datetime import UTC, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from ap_planner import discord_sync, services
from ap_planner.discord_bot import DiscordClient, DiscordError
from ap_planner.dsu import DSU_BASE
from ap_planner.dsu_api import API_CHUNK, ApiItem, DsuApiClient, DsuApiError, api_item
from ap_planner.dsu_web import EditablePlan
from ap_planner.ingest.store import WorldStore
from ap_planner.models.discord import DiscordConfig
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit

TZ = ZoneInfo("Europe/Berlin")
EDIT = f"{DSU_BASE}/tools/attackPlanner/7/edit/" + "E" * 40
SHOW = f"{DSU_BASE}/tools/attackPlanner/7/show/" + "S" * 40


def _op(**extra: object) -> Operation:
    data = {
        "name": "Test",
        "world": "de260",
        "arrival": "2026-11-12 18:18:55",
        "targets": [{"coord": "481|521", "offs": 1}],
        **extra,
    }
    return Operation.model_validate(data)


def _cmd(source: int = 1, send_min: int = 0, player: str = "Graf") -> PlannedCommand:
    arrival = datetime(2026, 11, 12, 18, 18, 54, 250_000, tzinfo=TZ)
    return PlannedCommand(
        source_id=source,
        target_id=2,
        units={Unit.AXE: 1183, Unit.RAM: 7},
        slowest_unit=Unit.RAM,
        type=CommandType.ATTACK,
        arrival=arrival,
        send=arrival - timedelta(hours=7) + timedelta(minutes=send_min),
        travel=timedelta(hours=7),
        note=f"{player} -> Ziel",
    )


# --- DS Ultimate API ----------------------------------------------------------------------


def test_api_item_format() -> None:
    item = api_item(_cmd())
    # seconds + separate ms, unit as index into DS Ultimate's unit list (ram = 8)
    assert item["arrival_time"] == int(datetime(2026, 11, 12, 17, 18, 54, tzinfo=UTC).timestamp())
    assert item["ms"] == 250
    assert item["slowest_unit"] == 8
    assert item["type"] == int(CommandType.ATTACK)
    assert (item["axe"], item["ram"], item["spear"]) == (1183, 7, 0)


@respx.mock
def test_create_sends_title_and_chunks_large_plans() -> None:
    created = {"id": 7, "edit": EDIT, "show": SHOW, "edit_key": "E" * 40, "errors": []}
    create = respx.post(f"{DSU_BASE}/toolAPI/attackPlanner/create").mock(
        return_value=httpx.Response(200, json=created)
    )
    more = respx.post(f"{DSU_BASE}/toolAPI/attackPlanner/createItems").mock(
        return_value=httpx.Response(200, json={"id": 7, "errors": []})
    )
    api = DsuApiClient("key", sleep=lambda _: None)
    info = api.create("de260", "ANGRIFFE 12.11. | Graf", [_cmd()] * (API_CHUNK + 5))
    body = json.loads(create.calls[0].request.content)
    assert (body["API_KEY"], body["server"], body["world"]) == ("key", "de", "260")
    assert body["title"] == "ANGRIFFE 12.11. | Graf"
    assert len(body["items"]) == API_CHUNK
    assert len(json.loads(more.calls[0].request.content)["items"]) == 5
    assert (info.edit_link, info.show_link, info.item_count) == (EDIT, SHOW, API_CHUNK + 5)


@respx.mock
def test_api_errors_are_readable() -> None:
    respx.post(f"{DSU_BASE}/toolAPI/attackPlanner/clear").mock(
        return_value=httpx.Response(403, json={"message": "Invalid API key"})
    )
    api = DsuApiClient("falsch", sleep=lambda _: None)
    with pytest.raises(DsuApiError, match="API-Key ungültig"):
        api.clear(EditablePlan.from_link(EDIT))


def test_no_key() -> None:
    with pytest.raises(DsuApiError):
        DsuApiClient("")


# --- progress -----------------------------------------------------------------------------


class FakeApi(DsuApiClient):
    def __init__(self, ticked: list[PlannedCommand]) -> None:
        self.ticked = ticked
        self.fetched: list[str] = []

    def fetch(self, link: str) -> tuple[str, list[ApiItem]]:
        self.fetched.append(link)
        return "t", [
            ApiItem(c.source_id, c.target_id, c.arrival.replace(microsecond=0), c.send, sent=True)
            for c in self.ticked
        ]


def test_progress_counts_ticks_and_overdue() -> None:
    done, late, soon = _cmd(1), _cmd(3, send_min=1), _cmd(4, send_min=30)
    plan = Plan(world="de260", name="t", created_at=datetime.now(UTC), commands=[done, late, soon])
    op = _op(dsu_links=[{"kind": "player", "key": "Graf", "show_link": SHOW}])
    now = late.send + timedelta(minutes=1)
    api = FakeApi([done])
    (p,), notes = services.dsu_progress(api, op, plan, now)
    assert notes == []
    assert api.fetched == [SHOW]
    assert (p.player, p.sent, p.total) == ("Graf", 1, 3)
    assert p.overdue == [late]
    assert p.upcoming == [soon]

    assert discord_sync.reminder_due(p, now, minutes=5)
    text = discord_sync.reminder_text(
        op, p, coords={3: "500|500", 4: "501|500", 2: "481|521"}, tz="Europe/Berlin",
        now=now, minutes=60,
    )  # fmt: skip
    assert "1/3" in text
    assert "`500|500`" in text  # overdue
    assert "`501|500`" in text  # due within 60 minutes


# --- private threads ----------------------------------------------------------------------


class FakeDiscord(DiscordClient):
    def __init__(self, missing: set[str] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.missing = missing or set()
        self._next = 100

    def send(self, channel_id: str, content: str, roles: tuple[str, ...] = ()) -> str:
        self._next += 1
        self.calls.append(("send", channel_id, content))
        return str(self._next)

    def edit(
        self, channel_id: str, message_id: str, content: str, roles: tuple[str, ...] = ()
    ) -> None:
        self.calls.append(("edit", channel_id, message_id, content))

    def create_private_thread(self, channel_id: str, name: str) -> str:
        self.calls.append(("thread", channel_id, name))
        return "T1"

    def add_thread_member(self, thread_id: str, user_id: str) -> None:
        self.calls.append(("member", thread_id, user_id))

    def dm_channel(self, user_id: str) -> str:
        self.calls.append(("dm", user_id))
        return f"dm{user_id}"

    def unarchive(self, thread_id: str) -> None:
        if thread_id in self.missing:
            raise DiscordError("weg", 404)
        self.calls.append(("unarchive", thread_id))


def test_thread_is_created_reused_and_edited() -> None:
    client = FakeDiscord()
    msg = discord_sync.Outgoing("thread", "Graf", None, ("55",), ["<@55> hi"], parent_id="P")
    op, action = discord_sync.deliver(client, _op(), msg)
    assert action == "gesendet"
    assert client.calls == [
        ("thread", "P", "Befehle Graf"),
        ("member", "T1", "55"),
        ("send", "T1", "<@55> hi"),
    ]
    cfg = discord_sync.remember_threads(DiscordConfig(), op)
    assert cfg.threads == {"Graf": "T1"}

    client.calls.clear()  # recomputed: same thread, reopened, message edited
    changed = discord_sync.Outgoing("thread", "Graf", "T1", ("55",), ["<@55> neu"], parent_id="P")
    op, action = discord_sync.deliver(client, op, changed)
    assert action == "bearbeitet + Hinweis"  # edits do not notify: new message pings
    assert client.calls[:2] == [("unarchive", "T1"), ("edit", "T1", "101", "<@55> neu")]
    assert client.calls[2][:2] == ("send", "T1")
    assert client.calls[2][2].startswith("<@55> ")


def test_next_operation_reuses_thread_and_recovers_deleted_one() -> None:
    client = FakeDiscord()
    msg = discord_sync.Outgoing("thread", "Graf", "OLD", ("55",), ["x"], parent_id="P")
    discord_sync.deliver(client, _op(), msg)
    assert client.calls[:2] == [("unarchive", "OLD"), ("member", "OLD", "55")]

    gone = FakeDiscord(missing={"OLD"})
    discord_sync.deliver(gone, _op(), msg)
    assert ("thread", "P", "Befehle Graf") in gone.calls


def test_threads_need_the_channel() -> None:
    plan = Plan(world="de260", name="t", created_at=datetime.now(UTC), commands=[_cmd()])
    cfg = DiscordConfig(spieler={"Graf": "55"})
    no_store = cast("WorldStore", None)  # not needed: fails before any lookup
    prepared = discord_sync.prepare(no_store, _op(), plan, cfg, "thread", tz="Europe/Berlin")
    assert prepared.messages == []
    assert "befehle" in prepared.missing[0]


def test_one_off_goes_to_thread_or_dm() -> None:
    cfg = DiscordConfig(spieler={"Graf": "55"}, threads={"Graf": "T9"})
    [dm] = discord_sync.to_player(cfg, "Graf", ["x"])
    assert dm.kind == "dm"
    cfg = cfg.model_copy(update={"kanaele": {"befehle": "P"}})
    [thread] = discord_sync.to_player(cfg, "Graf", ["x"])
    assert (thread.kind, thread.channel_id, thread.parent_id) == ("thread", "T9", "P")
    assert discord_sync.to_player(cfg, "Unbekannt", ["x"]) == []


# --- accounts played by several people --------------------------------------------


def test_config_accepts_one_or_several_ids() -> None:
    cfg = DiscordConfig.model_validate(
        {"spieler": {"Graf": "55", "Duo": "1, 2", "Trio": ["1", "2", 3, "2"]}}
    )
    assert cfg.spieler == {"Graf": ["55"], "Duo": ["1", "2"], "Trio": ["1", "2", "3"]}


def test_shared_account_thread_adds_and_pings_everyone() -> None:
    cfg = DiscordConfig(spieler={"Duo": ["1", "2"]}, kanaele={"befehle": "P"})
    [msg] = discord_sync.to_player(cfg, "Duo", ["x"])
    assert msg.user_ids == ("1", "2")
    client = FakeDiscord()
    discord_sync.deliver(client, _op(), msg)
    assert client.calls[:3] == [
        ("thread", "P", "Befehle Duo"),
        ("member", "T1", "1"),
        ("member", "T1", "2"),
    ]
    assert discord_sync.mentions(msg.user_ids) == "<@1> <@2>"


def test_shared_account_gets_one_dm_each() -> None:
    cfg = DiscordConfig(spieler={"Duo": ["1", "2"]})
    msgs = discord_sync.to_player(cfg, "Duo", ["x"])
    assert [(m.key, m.user_ids, m.player) for m in msgs] == [
        ("Duo", ("1",), "Duo"),  # first keeps the old key: earlier DMs are edited
        ("Duo@2", ("2",), "Duo"),
    ]
    client = FakeDiscord()
    op = _op()
    for m in msgs:
        op, _ = discord_sync.deliver(client, op, m)
    assert ("dm", "1") in client.calls
    assert ("dm", "2") in client.calls
    assert len(op.discord_messages) == 2
