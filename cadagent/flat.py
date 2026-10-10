"""Flat pattern: unfold a part with the standard K-factor method.

    L = A + B - 2(r + t) + (pi / 2) * (r + k * t)

A and B are the outside flange lengths, r the inner bend radius, t the thickness
and k the K-factor.

Flat pattern coordinates (mm), origin bottom-left:
  * plate:     x along the length (Flange A), y along the width.
  * L-bracket: x along the bend line (width), y along the developed length,
               starting at the free edge of Flange A and ending at the free
               edge of Flange B.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Part
from .rules import Rules


@dataclass(frozen=True)
class FlatHole:
    number: int
    x: float
    y: float
    diameter: float


@dataclass(frozen=True)
class FlatPattern:
    size_x: float
    size_y: float
    holes: list[FlatHole] = field(default_factory=list)
    # L-bracket only
    bend_line_y: float | None = None
    bend_allowance: float | None = None
    leg_a_flat: float | None = None
    leg_b_flat: float | None = None
    k_factor: float | None = None

    @property
    def flat_length(self) -> float:
        """The developed length (for a plate, simply its length)."""
        return self.size_y if self.bend_line_y is not None else self.size_x


def flat_length(a: float, b: float, r: float, t: float, k: float) -> float:
    return a + b - 2 * (r + t) + (math.pi / 2) * (r + k * t)


def unfold(part: Part, rules: Rules) -> FlatPattern:
    """Unfold a resolved, checked part."""
    if not part.is_bracket:
        holes = [FlatHole(i + 1, h.from_left, h.from_edge, h.diameter) for i, h in enumerate(part.holes)]
        return FlatPattern(size_x=part.flange_a, size_y=part.width, holes=holes)

    t, r = part.thickness, part.bend_radius
    bend = rules.bend_data(part.material, t)
    if bend is None or r is None or part.flange_b is None:
        raise ValueError("Cannot unfold: material, thickness or bend data is missing.")
    k = bend.k_factor
    allowance = (math.pi / 2) * (r + k * t)
    leg_a = part.flange_a - (r + t)
    leg_b = part.flange_b - (r + t)
    length = flat_length(part.flange_a, part.flange_b, r, t, k)
    holes = [
        FlatHole(i + 1, h.from_left, h.from_edge if h.flange == "A" else length - h.from_edge, h.diameter)
        for i, h in enumerate(part.holes)
    ]
    return FlatPattern(
        size_x=part.width,
        size_y=length,
        holes=holes,
        bend_line_y=leg_a + allowance / 2,
        bend_allowance=allowance,
        leg_a_flat=leg_a,
        leg_b_flat=leg_b,
        k_factor=k,
    )
