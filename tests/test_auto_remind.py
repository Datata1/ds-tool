"""Automatic reminders: every command is reminded once when due soon, overdue never."""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ap_planner import auto_remind, discord_sync, services, usecases
from ap_planner.config import Settings
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit


def _cmd(send_in_min: float) -> PlannedCommand:
    send = datetime.now(UTC) + timedelta(minutes=send_in_min)
    return PlannedCommand(
        source_id=1, target_id=4, units={Unit.AXE: 100}, slowest_unit=Unit.AXE,
        type=CommandType.ATTACK, arrival=send + timedelta(hours=1), send=send,
        travel=timedelta(hours=1), note="Graf -> D",
    )  # fmt: skip


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    settings = Settings(world="de260", data_dir=tmp_path / "data", discord_bot_token="x")
    folder = settings.world_dir / "ops" / "test"
    folder.mkdir(parents=True)
    op = Operation.model_validate(
        {"name": "T", "world": "de260", "arrival": "2026-11-12 09:00:00",
         "targets": [{"coord": "481|521", "offs": 1}]}
    )  # fmt: skip
    services.save_operation(op, folder / "operation.yaml")
    state: dict[str, Any] = {"cmd": _cmd(5), "sent": []}

    def progress(name: str) -> tuple[Operation, Plan, list[services.PlayerProgress], list[str]]:
        c = state["cmd"]
        overdue = [c] if c.send < datetime.now(UTC) else []
        upcoming = [] if overdue else [c]
        plan = Plan(world="de260", name="T", created_at=datetime.now(UTC), commands=[c])
        return op, plan, [services.PlayerProgress("Graf", 1, 0, overdue, upcoming)], []

    def to_player(_cfg: object, player: str, parts: list[str]) -> list[discord_sync.Outgoing]:
        return [discord_sync.Outgoing("dm", player, "c1", ("1",), parts)]

    class FakeClient:
        def __init__(self, _token: str) -> None: ...
        def close(self) -> None: ...

    monkeypatch.setattr(usecases, "settings", settings)
    monkeypatch.setattr(usecases, "_progress", progress)
    monkeypatch.setattr(usecases, "_store", lambda: None)
    monkeypatch.setattr(services, "plan_coords", lambda _s, _p: {1: "1|1", 4: "4|4"})
    monkeypatch.setattr(discord_sync, "to_player", to_player)
    monkeypatch.setattr(discord_sync, "post", lambda _c, m: state["sent"].append(m) or "c1")
    monkeypatch.setattr(usecases, "DiscordClient", FakeClient)
    return state


def _auto(name: str = "test") -> dict[str, Any]:
    return usecases._remind(name, 15, None, senden=True, nur_neue=True)


def test_each_stage_is_reminded_once(setup: dict[str, Any]) -> None:
    assert _auto()["erinnert"] == ["Graf"]  # due in 5 min
    assert "erinnert" not in _auto()  # same command, same stage: nothing new
    setup["cmd"] = setup["cmd"].model_copy(
        update={"send": datetime.now(UTC) - timedelta(minutes=1)}
    )
    assert "erinnert" not in _auto()  # now overdue: not reported (no spam)
    assert len(setup["sent"]) == 1
    # the manual button skips overdue commands too
    assert usecases.discord_remind("test", bestaetigt=True)["hinweis"] == "Niemand zu erinnern."
    setup["cmd"] = setup["cmd"].model_copy(
        update={"send": datetime.now(UTC) + timedelta(minutes=5)}
    )
    assert usecases.discord_remind("test", bestaetigt=True)["ergebnis"] == ["Graf: erinnert"]


def test_loop_runs_and_stops_when_finished() -> None:
    calls: list[int] = []

    def check() -> auto_remind.CheckResult:
        calls.append(1)
        return auto_remind.CheckResult(sent=["Graf"], finished=len(calls) >= 2)

    r = auto_remind.AutoReminder(check, interval_min=0.001, minutes=15, tz_label=lambda _d: "12:00")
    r.start()
    for _ in range(100):
        if not r.running:
            break
        time.sleep(0.02)
    assert not r.running
    assert len(calls) == 2
    assert r.state.log[0].startswith("12:00 fertig")
    assert "erinnert: Graf" in r.state.log[1]


def test_loop_survives_errors() -> None:
    def check() -> auto_remind.CheckResult:
        raise RuntimeError("DS Ultimate nicht erreichbar")

    r = auto_remind.AutoReminder(check, interval_min=1, minutes=15, tz_label=lambda _d: "12:00")
    r.start()
    for _ in range(100):
        if r.state.log:
            break
        time.sleep(0.02)
    assert r.running
    assert "DS Ultimate nicht erreichbar" in r.state.log[0]
    r.stop()
    assert not r.running
