from pathlib import Path

import pytest

from ap_planner.ingest import parse
from ap_planner.models.world import WorldConfig

FIXTURES = Path(__file__).parent / "fixtures" / "de260"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def world() -> WorldConfig:
    return parse.parse_world_config(
        "de260", (FIXTURES / "config.xml").read_bytes(), (FIXTURES / "units.xml").read_bytes()
    )
