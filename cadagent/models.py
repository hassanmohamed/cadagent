"""Part data: the numbers behind a part.

This is the single contract between the AI reader, the confirmation form, the
rule checks and the geometry templates. It is also what is written to part.json.

Dimension conventions (all in mm):
  * Flange lengths are outside dimensions; the L-bracket bend is 90 degrees.
  * L-bracket holes: `from_edge` is measured from the free edge of the hole's
    flange, `from_left` from the left side (along the bend line).
  * Plate holes: measured from the bottom-left corner, `from_edge` up from the
    bottom edge and `from_left` along the length. A plate's length is Flange A.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

PartType = Literal["plate", "l_bracket"]
Flange = Literal["A", "B"]


class Hole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flange: Flange = "A"
    from_edge: float
    from_left: float
    diameter: float


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_type: PartType
    name: str = ""
    material: str = ""
    thickness: float
    width: float
    flange_a: float
    flange_b: float | None = None
    bend_radius: float | None = None
    holes: list[Hole] = []

    @property
    def is_bracket(self) -> bool:
        return self.part_type == "l_bracket"


def fmt(value: float) -> str:
    """Format a dimension the way it is written on a drawing: 3, 12.5, 121.91."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text
