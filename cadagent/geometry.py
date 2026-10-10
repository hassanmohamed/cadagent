"""3D part templates (plate, L-bracket), STEP export and a mesh for the 3D view.

The AI never touches geometry: the solid is always built from these templates.

Model coordinates (mm):
  * plate:     x = length (Flange A), y = width, z = thickness.
  * L-bracket: x = width (along the bend line). Flange A lies flat, running in y
               from its free edge (y = 0) to the outside face of Flange B
               (y = A). Flange B stands up in z, from the outside face of
               Flange A (z = 0) to its free edge (z = B).
"""

from __future__ import annotations

import math
from pathlib import Path

import cadquery as cq

from .models import Part


def build_solid(part: Part) -> cq.Workplane:
    """Build the solid for a resolved, checked part."""
    return _build_bracket(part) if part.is_bracket else _build_plate(part)


def _build_plate(part: Part) -> cq.Workplane:
    solid = cq.Workplane("XY").box(part.flange_a, part.width, part.thickness, centered=False)
    for hole in part.holes:
        cutter = (
            cq.Workplane("XY")
            .workplane(offset=-1)
            .center(hole.from_left, hole.from_edge)
            .circle(hole.diameter / 2)
            .extrude(part.thickness + 2)
        )
        solid = solid.cut(cutter)
    return solid


def _build_bracket(part: Part) -> cq.Workplane:
    a, b, t, r, w = part.flange_a, part.flange_b, part.thickness, part.bend_radius, part.width
    ro = r + t  # outer bend radius
    s = math.sqrt(0.5)
    cy, cz = a - ro, ro  # bend centre in the y-z profile plane

    # The L profile is drawn in the YZ plane (local x = model y, local y = model z)
    # and extruded along the model x axis, the bend line.
    profile = (
        cq.Workplane("YZ")
        .moveTo(0, 0)
        .lineTo(a - ro, 0)
        .threePointArc((cy + ro * s, cz - ro * s), (a, ro))
        .lineTo(a, b)
        .lineTo(a - t, b)
        .lineTo(a - t, ro)
        .threePointArc((cy + r * s, cz - r * s), (a - ro, t))
        .lineTo(0, t)
        .close()
    )
    solid = profile.extrude(w)

    for hole in part.holes:
        radius = hole.diameter / 2
        if hole.flange == "A":
            cutter = (
                cq.Workplane("XY")
                .workplane(offset=-1)
                .center(hole.from_left, hole.from_edge)
                .circle(radius)
                .extrude(t + 2)
            )
        else:
            # XZ workplane: local x = model x, local y = model z, normal = -y.
            cutter = (
                cq.Workplane("XZ")
                .workplane(offset=-(a + 1))
                .center(hole.from_left, b - hole.from_edge)
                .circle(radius)
                .extrude(t + 2)
            )
        solid = solid.cut(cutter)
    return solid


def expected_volume(part: Part) -> float:
    """Closed-form volume, used to cross-check the solid."""
    t = part.thickness
    holes = sum(math.pi * (h.diameter / 2) ** 2 * t for h in part.holes)
    if not part.is_bracket:
        return part.flange_a * part.width * t - holes
    r = part.bend_radius
    ro = r + t
    area = t * (part.flange_a - ro) + t * (part.flange_b - ro) + math.pi / 4 * (ro**2 - r**2)
    return area * part.width - holes


def export_step(solid: cq.Workplane, path: Path) -> None:
    cq.exporters.export(solid, str(path), exportType="STEP")


def mesh(solid: cq.Workplane) -> dict:
    """Triangles for shading plus edge polylines for crisp CAD-style outlines."""
    shape = solid.val()
    vertices, triangles = shape.tessellate(0.05, 0.2)
    positions = [round(c, 4) for v in vertices for c in (v.x, v.y, v.z)]
    indices = [i for tri in triangles for i in tri]

    edges: list[list[float]] = []
    for edge in shape.Edges():
        steps = 1 if edge.geomType() == "LINE" else 32
        points = [edge.positionAt(i / steps) for i in range(steps + 1)]
        edges.append([round(c, 4) for p in points for c in (p.x, p.y, p.z)])

    box = shape.BoundingBox()
    return {
        "positions": positions,
        "indices": indices,
        "edges": edges,
        "bbox": {"min": [box.xmin, box.ymin, box.zmin], "max": [box.xmax, box.ymax, box.zmax]},
    }
