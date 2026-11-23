import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from ap_planner import discord_sync
from ap_planner.discord_bot import API, DiscordClient, DiscordError, Member
from ap_planner.export.announce import discord_player_dm, discord_players
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit

TZ = ZoneInfo("Europe/Berlin")


def _op() -> Operation:
    return Operation.model_validate(
        {
            "name": "Test",
            "world": "de260",
            "arrival": "2026-11-12 18:18:55",
            "targets": [{"coord": "481|521", "offs": 1}],
        }
    )


def _cmd(origin: str = "main") -> PlannedCommand:
    arrival = datetime(2026, 11, 12, 18, 18, 54, tzinfo=TZ)
    return PlannedCommand(
        source_id=1,
        target_id=2,
        units={Unit.AXE: 1183, Unit.RAM: 7},
        slowest_unit=Unit.RAM,
        type=CommandType.ATTACK,
        arrival=arrival,
        send=arrival - timedelta(hours=7),
        travel=timedelta(hours=7),
        note="Graf -> PlsDontCry",
        origin=origin,
    )


# --- bot client -----------------------------------------------------------------


@respx.mock
def test_send_retries_after_rate_limit() -> None:
    route = respx.post(f"{API}/channels/42/messages").mock(
        side_effect=[
            httpx.Response(429, json={"retry_after": 0.5}),
            httpx.Response(200, json={"id": "777"}),
        ]
    )
    waited: list[float] = []
    client = DiscordClient("tok", sleep=waited.append)
    assert client.send("42", "hallo") == "777"
    assert route.call_count == 2
    assert waited == [0.6]
    body = json.loads(route.calls.last.request.content)
    assert body["allowed_mentions"] == {"parse": ["users"]}  # never @everyone
    assert route.calls.last.request.headers["Authorization"] == "Bot tok"


@respx.mock
def test_missing_rights_are_explained() -> None:
    respx.post(f"{API}/users/@me/channels").mock(
        return_value=httpx.Response(403, json={"message": "Cannot send messages to this user"})
    )
    with pytest.raises(DiscordError, match="Rechte"):
        DiscordClient("tok").dm_channel("5")


def test_no_token() -> None:
    with pytest.raises(DiscordError, match="AP_DISCORD_BOT_TOKEN"):
        DiscordClient("")


@respx.mock
def test_members_skip_bots() -> None:
    respx.get(url__startswith=f"{API}/guilds/9/members").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"user": {"id": "1", "username": "graf", "global_name": "Graf"}, "nick": None},
                {"user": {"id": "2", "username": "botty", "bot": True}},
            ],
        )
    )
    members = DiscordClient("tok").members("9")
    assert [m.id for m in members] == ["1"]


# --- matching and texts ---------------------------------------------------------------


def test_suggest_member() -> None:
    members = [
        Member("1", "graf_s", "Graf Scheisser", None),
        Member("2", "sueaa", None, "Suea | RAK"),
        Member("3", "someone", None, None),
    ]
    graf = discord_sync.suggest_member("Graf Scheißer", members)
    suea = discord_sync.suggest_member("Suea", members)
    assert graf is not None
    assert graf.id == "1"
    assert suea is not None
    assert suea.id == "2"
    assert discord_sync.suggest_member("PlsDontCry", members) is None


def test_dm_lists_commands_and_running() -> None:
    text = discord_player_dm(
        _op(),
        "Graf",
        [_cmd(), _cmd("kept:manual:running")],
        {1: "478|535", 2: "481|521"},
        "Europe/Berlin",
    )
    assert "**12.11. 11:18:54** losschicken" in text
    assert "`478|535` → `481|521`" in text
    assert "1183 Axt" in text
    assert "läuft schon" in text
    assert "_(Link folgt)_" in text


# --- deliver: send once, then edit ------------------------------------------------------


class FakeDiscord(DiscordClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._next = 100

    def send(self, channel_id: str, content: str, roles: tuple[str, ...] = ()) -> str:
        self._next += 1
        self.calls.append(("send", channel_id, content))
        return str(self._next)

    def edit(
        self, channel_id: str, message_id: str, content: str, roles: tuple[str, ...] = ()
    ) -> None:
        self.calls.append(("edit", channel_id, message_id, content))

    def delete(self, channel_id: str, message_id: str) -> None:
        self.calls.append(("delete", channel_id, message_id))

    def dm_channel(self, user_id: str) -> str:
        self.calls.append(("dm", user_id))
        return f"dm{user_id}"

    def unarchive(self, thread_id: str) -> None:
        self.calls.append(("unarchive", thread_id))

    def add_thread_member(self, thread_id: str, user_id: str) -> None:
        self.calls.append(("member", thread_id, user_id))

    def create_private_thread(self, parent_id: str, name: str) -> str:
        self.calls.append(("thread", parent_id, name))
        return "t1"


def test_deliver_sends_then_edits_then_skips() -> None:
    client = FakeDiscord()
    msg = discord_sync.Outgoing("dm", "Graf", None, ("55",), ["teil 1", "teil 2"])
    op, action = discord_sync.deliver(client, _op(), msg)
    assert action == "gesendet"
    assert client.calls[0] == ("dm", "55")
    saved = op.sent_message("dm", "Graf")
    assert saved is not None
    assert saved.message_ids == ["101", "102"]

    client.calls.clear()
    op, action = discord_sync.deliver(client, op, msg)
    assert action == "unverändert"
    assert client.calls == []

    shorter = discord_sync.Outgoing("dm", "Graf", None, ("55",), ["neu"])
    op, action = discord_sync.deliver(client, op, shorter)
    assert action == "bearbeitet + Hinweis"
    assert client.calls[:2] == [("edit", "dm55", "101", "neu"), ("delete", "dm55", "102")]
    assert client.calls[2][:2] == ("send", "dm55")
    assert "wurde aktualisiert" in client.calls[2][2]
    saved = op.sent_message("dm", "Graf")
    assert saved is not None
    assert saved.message_ids == ["101"]
    assert len(op.discord_messages) == 1


def test_dm_falls_back_to_target_plan() -> None:
    show = "https://ds-ultimate.de/tools/attackPlanner/1/show/" + "S" * 40
    data = _op().model_dump(mode="json")
    data["dsu_links"] = [{"kind": "target", "key": "481|521", "show_link": show}]
    op = Operation.model_validate(data)
    text = discord_player_dm(op, "Graf", [_cmd()], {1: "478|535", 2: "481|521"}, "Europe/Berlin")
    assert f"Plan: `481|521` <{show}>" in text


def test_announcement_reveals_no_targets_or_fakes() -> None:
    op = _op()
    fake = _cmd().model_copy(update={"type": CommandType.FAKE, "note": "Suea -> X"})
    plan = Plan(world="de260", name="Test", created_at=datetime.now(TZ), commands=[_cmd(), fake])
    text = discord_players(op, plan, "Europe/Berlin")
    assert "OP Test" in text
    assert "12.11. 11:18" in text  # send window
    for secret in ("481|521", "http", "Graf", "Suea", "Befehl ("):
        assert secret not in text


def test_thread_update_pings_players() -> None:
    client = FakeDiscord()
    msg = discord_sync.Outgoing("thread", "Graf", None, ("55", "66"), ["alt"], parent_id="9")
    op, action = discord_sync.deliver(client, _op(), msg)
    assert action == "gesendet"
    assert discord_sync.planned_action(op, msg) == "unverändert"

    changed = discord_sync.Outgoing("thread", "Graf", "t1", ("55", "66"), ["neu"], parent_id="9")
    assert discord_sync.planned_action(op, changed) == "bearbeiten + Hinweis"
    client.calls.clear()
    op, action = discord_sync.deliver(client, op, changed)
    assert action == "bearbeitet + Hinweis"
    assert ("edit", "t1", "101", "neu") in client.calls
    notice = client.calls[-1]
    assert notice[:2] == ("send", "t1")
    assert notice[2].startswith("<@55> <@66> ")
    assert "neu laden" in notice[2]
    assert op.sent_message("thread", "Graf").message_ids == ["101"]  # notice not tracked
