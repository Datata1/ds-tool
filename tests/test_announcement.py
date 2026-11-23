"""Public announcement at the final plan: into the thread channel, pings stamm + wing roles."""

import gzip
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ap_planner import discord_sync
from ap_planner.discord_bot import DiscordClient, Role, allowed_mentions
from ap_planner.export.announce import discord_players
from ap_planner.ingest.store import WorldStore
from ap_planner.models.discord import DiscordConfig
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit

TZ = "Europe/Berlin"
ALLIES = "1,Raketen,RAK,2,3,0,0,1\n2,Feind,SWRE,1,1,0,0,2\n"
PLAYERS = "10,Graf,1,2,0,1\n11,Suea,1,1,0,2\n20,Basol,2,1,0,3\n"
VILLAGES = "1,A,478,535,10,5000,0\n3,C,484,530,11,9000,0\n4,D,481,521,20,4000,0\n"
T0 = datetime(2026, 11, 12, 9, 0, 0, tzinfo=ZoneInfo(TZ))


@pytest.fixture
def store(tmp_path: Path, fixtures_dir: Path) -> WorldStore:
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("config.xml", "units.xml"):
        shutil.copy(fixtures_dir / name, raw / name)
    for name, text in (("ally", ALLIES), ("player", PLAYERS), ("village", VILLAGES)):
        (raw / f"{name}.txt.gz").write_bytes(gzip.compress(text.encode()))
    s = WorldStore(tmp_path / "w.sqlite")
    s.load_raw(raw, "de260")
    return s


def _op() -> Operation:
    return Operation.model_validate(
        {
            "name": "RAK Aktion",
            "world": "de260",
            "arrival": "2026-11-12 09:00:00",
            "targets": [{"coord": "481|521", "offs": 1}],
        }
    )


def _plan() -> Plan:
    def cmd(kind: CommandType, arrival: datetime, who: str) -> PlannedCommand:
        return PlannedCommand(
            source_id=1,
            target_id=4,
            units={Unit.AXE: 5000, Unit.RAM: 200},
            slowest_unit=Unit.RAM,
            type=kind,
            arrival=arrival,
            send=arrival - timedelta(hours=3),
            travel=timedelta(hours=3),
            note=f"{who} -> D",
        )

    cmds = [
        cmd(CommandType.ATTACK, T0, "Graf"),
        cmd(CommandType.FAKE, T0 + timedelta(minutes=4), "Suea"),
    ]
    return Plan.model_validate(
        {"world": "de260", "name": "Test", "created_at": datetime.now(UTC), "commands": cmds}
    )


def test_roles_matched_by_tag_not_hardcoded() -> None:
    roles = [
        Role("1", "Admin", mentionable=False),
        Role("2", "[RAK]", mentionable=True),
        Role("3", "RAKK", mentionable=False),
        Role("4", "rakkk", mentionable=True),
    ]
    match = discord_sync.match_roles(roles, ["RAK", "RAKK", "RAKKK", "WING2"])
    assert match.found == {"RAK": "2", "RAKK": "3", "RAKKK": "4"}  # RAK never grabs RAKK
    assert match.missing == ["WING2"]
    assert match.not_mentionable == ["RAKK"]
    report = discord_sync.role_report(match)
    assert report["erwaehnt"] == ["@RAK", "@RAKK", "@RAKKK"]
    assert "WING2" in str(report["keine_rolle"])


def test_announcement_calls_for_fakes_without_details() -> None:
    text = discord_players(_op(), _plan(), TZ, enemies=["SWRE"], ping="<@&2> <@&3>")
    assert text.startswith("<@&2> <@&3>\n**OP RAK Aktion**")
    assert "Fakes" in text
    assert "**SWRE**" in text
    assert "**12.11. 09:00** bis **12.11. 09:04**" in text  # landing window, minutes only
    for secret in ("481|521", "http", "Graf", "Suea", "Basol", "D "):  # nobody unassigned
        assert secret not in text


def test_spieler_goes_to_thread_channel_and_may_ping_roles(store: WorldStore) -> None:
    cfg = DiscordConfig(
        kanaele={"befehle": "B", "ankuendigung": "A"}, rollen={"RAK": "2", "RAKK": "3"}
    )
    prepared = discord_sync.prepare(store, _op(), _plan(), cfg, "spieler", tz=TZ)
    (msg,) = prepared.messages
    assert (msg.key, msg.channel_id, msg.role_ids) == ("befehle", "B", ("2", "3"))
    assert msg.parts[0].startswith("<@&2> <@&3>")
    assert "**SWRE**" in msg.parts[0]  # enemy tribe read from the world data

    # without a thread channel it still uses the announcement channel
    cfg = DiscordConfig(kanaele={"ankuendigung": "A"})
    (msg,) = discord_sync.prepare(store, _op(), _plan(), cfg, "spieler", tz=TZ).messages
    assert (msg.key, msg.channel_id, msg.role_ids) == ("ankuendigung", "A", ())


class _Recorder(DiscordClient):
    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[str, ...]]] = []

    def send(self, channel_id: str, content: str, roles: tuple[str, ...] = ()) -> str:
        self.sent.append((channel_id, roles))
        return "m1"


def test_deliver_passes_role_ids() -> None:
    msg = discord_sync.Outgoing("spieler", "befehle", "B", (), ["hi"], role_ids=("2",))
    client = _Recorder()
    discord_sync.deliver(client, _op(), msg)
    assert client.sent == [("B", ("2",))]


def test_allowed_mentions_never_mass_pings() -> None:
    assert allowed_mentions() == {"parse": ["users"]}
    assert allowed_mentions(("2",)) == {"parse": ["users"], "roles": ["2"]}


def test_unassigned_accounts_asked_to_contact_sf(store: WorldStore) -> None:
    cfg = DiscordConfig(kanaele={"befehle": "B"}, spieler={"Graf": ["55"]})
    assert discord_sync.unassigned_players(_plan(), cfg) == ["Suea"]
    (msg,) = discord_sync.prepare(store, _op(), _plan(), cfg, "spieler", tz=TZ).messages
    assert "bei der SF melden" in msg.parts[0]
    assert "**Suea**" in msg.parts[0]

    # everyone assigned: no such paragraph
    cfg = DiscordConfig(kanaele={"befehle": "B"}, spieler={"Graf": ["55"], "Suea": ["66"]})
    (msg,) = discord_sync.prepare(store, _op(), _plan(), cfg, "spieler", tz=TZ).messages
    assert "SF melden" not in msg.parts[0]
