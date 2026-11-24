from pathlib import Path

import yaml

from ap_planner import services
from ap_planner.models.operation import TargetOrder
from ap_planner.models.profile import Profile, deep_merge
from ap_planner.models.world import Unit


def test_deep_merge_override_wins() -> None:
    base = {"a": 1, "n": {"x": 1, "y": 2}}
    assert deep_merge(base, {"n": {"y": 3}, "b": 2}) == {"a": 1, "n": {"x": 1, "y": 3}, "b": 2}


def test_operation_inherits_profile(tmp_path: Path) -> None:
    world_dir = tmp_path / "de999"
    services.save_profile(
        Profile(world="de999", own_tribes=["ABC"], off_min_pop=7000,
                home_guard={Unit.SPEAR: 50}),
        world_dir,
    )  # fmt: skip
    op_file = world_dir / "ops" / "test" / "operation.yaml"
    op_file.parent.mkdir(parents=True)
    op_file.write_text(
        yaml.safe_dump(
            {
                "name": "t",
                "arrival": "2026-11-10 08:00:00",
                "off_settings": {"units": ["axe", "light", "ram"]},
                "targets": [{"coord": "500|500", "offs": 1}],
            }
        )
    )
    op = services.load_operation(op_file)
    assert op.world == "de999"
    assert op.participants.allies == ["ABC"]
    assert op.off_settings.min_pop == 7000  # from profile
    assert op.off_settings.units == [Unit.AXE, Unit.LIGHT, Unit.RAM]  # operation wins
    assert op.home_guard == {Unit.SPEAR: 50}
    assert str(op.targets[0].coord) == "500|500"


def test_examples_are_valid() -> None:
    root = Path(__file__).parent.parent / "examples"
    Profile.model_validate(yaml.safe_load((root / "profil.beispiel.yaml").read_text()))
    from ap_planner.models.operation import Operation  # noqa: PLC0415

    data = yaml.safe_load((root / "operation.beispiel.yaml").read_text())
    op = Operation.model_validate({"world": "de260", **data})
    assert len(op.targets) == 4


def test_manual_attack_parses() -> None:
    t = TargetOrder.model_validate(
        {"coord": "481|532", "nobles": 1, "manual_attacks": [{"coord": "507|505"}]}
    )
    assert t.manual_attacks[0].slowest_unit == Unit.AXE
    assert t.manual_attacks[0].kind == "attack"


def test_manual_only_target_with_running_noble() -> None:
    t = TargetOrder.model_validate(
        {
            "coord": "480|529",
            "manual_attacks": [
                {"coord": "489|518", "slowest_unit": "ram", "running": True},
                {"coord": "478|535", "slowest_unit": "snob", "kind": "noble"},
            ],
        }
    )
    assert t.manual_attacks[0].running
    assert t.manual_attacks[1].kind == "noble"
