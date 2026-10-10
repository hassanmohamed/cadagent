import json
from pathlib import Path

import pytest

from cadagent.models import Hole, Part
from cadagent.rules import Rules

ROOT = Path(__file__).resolve().parent.parent
TEST_DATA = ROOT / "test_data"


@pytest.fixture(scope="session")
def rules() -> Rules:
    return Rules.load()


@pytest.fixture(scope="session")
def answer_key() -> dict:
    return json.loads((TEST_DATA / "answer_key.json").read_text())["files"]


@pytest.fixture
def bracket() -> Part:
    return Part(
        part_type="l_bracket", name="BRK-001", material="Steel S235", thickness=3, width=60,
        flange_a=80, flange_b=50, bend_radius=3,
        holes=[
            Hole(flange="A", from_edge=20, from_left=15, diameter=9),
            Hole(flange="A", from_edge=20, from_left=45, diameter=9),
            Hole(flange="B", from_edge=20, from_left=30, diameter=11),
        ],
    )


@pytest.fixture
def plate() -> Part:
    return Part(
        part_type="plate", name="PLT-001", material="Steel S235", thickness=3, width=80, flange_a=120,
        holes=[Hole(from_edge=15, from_left=15, diameter=9), Hole(from_edge=40, from_left=60, diameter=20)],
    )
