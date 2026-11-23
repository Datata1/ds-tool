# ruff: noqa: RUF001
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ap_planner.export.aktion import SEPARATOR, AktionOp, aktion_markdown, aktion_messages
from ap_planner.export.announce import TargetInfo
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit

TZ = ZoneInfo("Europe/Berlin")
ARR = datetime(2026, 11, 16, 9, 28, 0, tzinfo=TZ)
DSU = "https://ds-ultimate.de/tools/attackPlanner"


def _cmd(player: str, ctype: CommandType, send_h: int, arrival: datetime = ARR) -> PlannedCommand:
    send = arrival - timedelta(hours=send_h)
    return PlannedCommand(
        source_id=1, target_id=99, units={Unit.AXE: 100}, slowest_unit=Unit.AXE, type=ctype,
        arrival=arrival, send=send, travel=arrival - send, note=f"{player} -> Ebert",
    )  # fmt: skip


def _setup(with_player_links: bool = True) -> AktionOp:
    links = [
        {"kind": "target", "key": "486|509", "title": "ADELN 16.11. | Ziel 486|509 Ebert",
         "show_link": f"{DSU}/1/show/s", "edit_link": f"{DSU}/1/edit/e"},
    ]  # fmt: skip
    if with_player_links:
        links.append(
            {
                "kind": "player",
                "key": "Bobby",
                "show_link": f"{DSU}/2/show/s",
                "edit_link": f"{DSU}/2/edit/e",
            }
        )
    op = Operation.model_validate(
        {"name": "RAKK ADELN", "world": "de260", "arrival": "2026-11-16 09:28:00",
         "targets": [{"coord": "486|509", "offs": 1, "nobles": 2}],
         "gdoc_id": "1tXkbr8ENezuiRC6Nc2V7RS6kihK4LjLUIUjDwwNthZQ", "dsu_links": links}
    )  # fmt: skip
    plan = Plan(
        world="de260", name="t", created_at=ARR,
        commands=[
            _cmd("Bobby", CommandType.ATTACK, 9, ARR - timedelta(seconds=1)),
            _cmd("Bobby", CommandType.CONQUEST, 8),
            _cmd("Intmeister07", CommandType.CONQUEST, 5),
        ],
    )  # fmt: skip
    return AktionOp(op, plan, [TargetInfo("486|509", 99, "Ebert", "Ebert", "SWRE")])


def test_aktion_layout_and_edit_links() -> None:
    text = aktion_markdown([_setup()], "Europe/Berlin")
    assert "**RAKK ADELN** (Review) – Einschlag Mo 16.11." in text
    assert "📄 Doc: <https://docs.google.com/document/d/1tXk" in text
    assert (
        "- **ADELN 09:27:59 / 09:28:00** 486|509 (Ebert) → geht an **Intmeister07** · "
        f"1 Off, 2 AGs (Bobby, Intmeister07): <{DSU}/1/edit/e>"
    ) in text
    assert f"- Bobby (1 Off, 1 AG, Mo 16.11. 00:27:59–01:28:00): <{DSU}/2/edit/e>" in text
    assert "- Intmeister07 (1 AG, Mo 16.11. 04:28:00): ⚠️ kein Bearbeiten-Link" in text
    assert "/show/" not in text
    assert text.count(SEPARATOR) == 1


def test_aktion_splits_below_discord_limit() -> None:
    a = _setup()
    many = [_cmd(f"Spieler{i:03}", CommandType.FAKE, 3) for i in range(80)]
    a = AktionOp(a.op, a.plan.model_copy(update={"commands": many}), a.targets)
    msgs = aktion_messages([a], "Europe/Berlin")
    assert len(msgs) > 2
    assert all(len(m) <= 1900 for m in msgs)
