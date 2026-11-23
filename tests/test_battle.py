import pytest

from ap_planner.domain.battle import Wave, blocked, deff_needed, fight, run_train
from ap_planner.models.world import Unit, WorldConfig

OFF = {Unit.AXE: 3176, Unit.LIGHT: 1258, Unit.RAM: 65, Unit.CATAPULT: 50}
DEFF = {Unit.SPEAR: 3000, Unit.SWORD: 3000}
AG = {Unit.SNOB: 1, Unit.AXE: 100}


def test_fight_formula(world: WorldConfig) -> None:
    r = fight(world, OFF, DEFF, wall=20)
    assert r.attack == pytest.approx(295_710)
    # weighted defense x 1.037^20 + 20 + 50*20
    assert r.defense == pytest.approx(203_291 * 1.037**20 + 1020, rel=1e-3)
    assert not r.attacker_won
    survivors = (1 - (r.attack / r.defense) ** 1.5) * 3000
    assert r.defender_left[Unit.SPEAR] == round(survivors)


def test_night_bonus_and_morale_weaken_the_attack(world: WorldConfig) -> None:
    small = {Unit.SPEAR: 1000, Unit.SWORD: 1000}
    assert fight(world, OFF, small, wall=0).attacker_won
    assert not fight(world, OFF, small, wall=0, night=True, morale=0.3).attacker_won


def test_train_and_deff_needed(world: WorldConfig) -> None:
    waves = [Wave("Off", OFF, is_noble=False, night=False)] + [
        Wave(f"AG{i}", AG, is_noble=True, night=False) for i in range(5)
    ]
    assert run_train(world, waves, {}, wall=0, wall_ags=0).ags_through == 5
    assert blocked(2)
    assert not blocked(3)
    assert blocked(3, sure=False)
    assert not blocked(4, sure=False)
    k = deff_needed(world, waves, {Unit.SPEAR: 1000, Unit.SWORD: 1000}, wall=20, wall_ags=20)
    assert k is not None
    package = {Unit.SPEAR: 1000, Unit.SWORD: 1000}
    just = {u: round(n * k) for u, n in package.items()}
    less = {u: round(n * (k - 0.05)) for u, n in package.items()}
    assert blocked(run_train(world, waves, just, wall=20, wall_ags=20).ags_through)
    assert not blocked(run_train(world, waves, less, wall=20, wall_ags=20).ags_through)
