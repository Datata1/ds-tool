import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ap_planner.export.announce import split_discord
from ap_planner.export.workbench import to_workbench, to_workbench_line
from ap_planner.models.plan import CommandType, PlannedCommand
from ap_planner.models.world import Unit
from ap_planner.services import dsu_create_url


def _cmd() -> PlannedCommand:
    arrival = datetime(2026, 11, 7, 9, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    return PlannedCommand(
        source_id=1,
        target_id=2,
        units={Unit.AXE: 6000, Unit.LIGHT: 3000, Unit.RAM: 300, Unit.SNOB: 1},
        slowest_unit=Unit.SNOB,
        type=CommandType.CONQUEST,
        arrival=arrival,
        send=arrival - timedelta(hours=2),
        travel=timedelta(hours=2),
    )


def test_line_matches_dsu_export_format() -> None:
    line = to_workbench_line(_cmd())
    parts = line.split("&")
    assert parts[:3] == ["1", "2", "snob"]
    # 2026-11-07 09:00:00 CET == 08:00:00 UTC
    assert parts[3] == "1794038400000"
    assert parts[4:7] == ["11", "false", "false"]
    units = dict(u.split("=", 1) for u in parts[7].split("/"))
    assert list(units) == [
        "spear", "sword", "axe", "archer", "spy", "light", "marcher",
        "heavy", "ram", "catapult", "knight", "snob", "militia",
    ]  # fmt: skip
    decoded = {k: int(base64.b64decode(v)) for k, v in units.items()}
    assert decoded["axe"] == 6000
    assert decoded["snob"] == 1
    assert decoded["spear"] == 0
    assert units["militia"] == "MA=="


def test_unit_counts_never_contain_separator() -> None:
    # DSU splits the unit block on "/", so encoded counts must never contain it.
    for n in range(200_000):
        assert "/" not in base64.b64encode(str(n).encode()).decode()


def test_multiple_lines() -> None:
    out = to_workbench([_cmd(), _cmd()])
    assert out.count("\n") == 2


def test_dsu_create_url() -> None:
    assert dsu_create_url("de260") == "https://ds-ultimate.de/tools/create/attackPlanner/de/260"


def test_split_discord_keeps_blocks_together() -> None:

    blocks = [f"**Ziel {i}**\n> " + "x" * 300 for i in range(10)]
    parts = split_discord("\n\n".join(blocks), limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "\n\n".join(parts) == "\n\n".join(blocks)


def test_attack_label() -> None:
    from ap_planner.services import attack_label  # noqa: PLC0415

    noble = _cmd()  # CONQUEST
    fake = noble.model_copy(update={"type": CommandType.FAKE})
    off = noble.model_copy(update={"type": CommandType.ATTACK})
    assert attack_label([fake, noble]) == "ADELN"
    assert attack_label([fake, off]) == "OFF"
    assert attack_label([fake, fake]) == "FAKE"
