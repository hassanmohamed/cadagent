"""Engineering rules: load the rules file and check a part against it.

Problems are reported in plain words. Two severities:
  * "error": the part cannot be built (missing or impossible geometry).
  * "rule":  the part can be built but breaks an engineering rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from .models import Part, fmt

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "rules.yaml"


LIMIT_KEYS = [
    "min_hole_diameter",
    "min_hole_edge_to_part_edge",
    "min_hole_edge_to_bend",
    "min_hole_edge_to_hole_edge",
]


class RulesError(Exception):
    """rules.yaml is broken. The message says what to fix, in plain words."""


class Issue(BaseModel):
    severity: Literal["error", "rule"]
    field: str | None = None
    message: str


@dataclass(frozen=True)
class BendData:
    bend_radius: float
    k_factor: float


class Rules:
    def __init__(self, data: dict):
        _validate(data)
        self.data = data
        self.version: str = str(data.get("version", ""))
        self.materials: list[dict] = data["materials"]
        self.defaults: dict = data["defaults"]
        self.limits: dict = data["limits"]
        self.flat_length_tolerance: float = float(data.get("flat_length_tolerance_mm", 0.1))

    @classmethod
    def load(cls, path: Path = RULES_PATH) -> "Rules":
        try:
            data = yaml.safe_load(path.read_text())
        except FileNotFoundError as exc:
            raise RulesError(f"The rules file is missing: {path}") from exc
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f" near line {mark.line + 1}" if mark else ""
            raise RulesError(
                f"The rules file ({path.name}) could not be read{where}. Check the indentation and colons."
            ) from exc
        return cls(data)

    def material_names(self) -> list[str]:
        return [m["name"] for m in self.materials]

    def find_material(self, name: str) -> dict | None:
        wanted = name.strip().lower()
        for material in self.materials:
            names = [material["name"], *material.get("aliases", [])]
            if wanted in (n.lower() for n in names):
                return material
        return None

    def canonical_material(self, name: str) -> str:
        """Map an alias such as "S235" onto the name used in the rules table."""
        material = self.find_material(name)
        return material["name"] if material else name

    def thicknesses(self, material_name: str) -> list[float]:
        material = self.find_material(material_name)
        return sorted(float(t) for t in material["thicknesses"]) if material else []

    def bend_data(self, material_name: str, thickness: float) -> BendData | None:
        material = self.find_material(material_name)
        if not material:
            return None
        for t, row in material["thicknesses"].items():
            if abs(float(t) - thickness) < 1e-6:
                return BendData(float(row["bend_radius"]), float(row["k_factor"]))
        return None

    def limit(self, key: str, thickness: float) -> float:
        row = self.limits[key]
        return max(float(row.get("mm", 0)), float(row.get("times_thickness", 0)) * thickness)

    def summary(self) -> dict:
        """What the web page needs to build its dropdowns."""
        return {
            "version": self.version,
            "materials": [
                {"name": m["name"], "thicknesses": self.thicknesses(m["name"])} for m in self.materials
            ],
            "defaults": self.defaults,
            "flat_length_tolerance_mm": self.flat_length_tolerance,
        }


def _validate(data: object) -> None:
    """Catch typing mistakes in rules.yaml before they turn into confusing errors."""

    def fail(message: str) -> None:
        raise RulesError(f"Problem in rules.yaml: {message}")

    def number(value: object, what: str, minimum: float = 0.0, strict: bool = False) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail(f"{what} must be a number, but is {value!r}.")
        if value < minimum or (strict and value <= minimum):
            fail(f"{what} must be {'greater than' if strict else 'at least'} {minimum:g}, but is {value:g}.")
        return float(value)

    if not isinstance(data, dict):
        fail("the file is empty or is not a list of settings.")
    materials = data.get("materials")
    if not isinstance(materials, list) or not materials:
        fail('"materials" must list at least one material.')
    names: dict[str, list[float]] = {}
    for material in materials:
        name = material.get("name") if isinstance(material, dict) else None
        if not name or not isinstance(name, str):
            fail("every material needs a name.")
        table = material.get("thicknesses")
        if not isinstance(table, dict) or not table:
            fail(f'material "{name}" needs at least one thickness.')
        for thickness, row in table.items():
            what = f'material "{name}", thickness {thickness}'
            number(thickness, f"{what}: the thickness", strict=True)
            if not isinstance(row, dict) or "bend_radius" not in row or "k_factor" not in row:
                fail(f"{what} needs both bend_radius and k_factor.")
            number(row["bend_radius"], f"{what}: bend_radius", strict=True)
            k = number(row["k_factor"], f"{what}: k_factor", strict=True)
            if k > 1:
                fail(f"{what}: k_factor must be between 0 and 1, but is {k:g}.")
        if not isinstance(material.get("aliases", []), list):
            fail(f'material "{name}": aliases must be a list.')
        names[name] = [float(t) for t in table]

    defaults = data.get("defaults")
    if not isinstance(defaults, dict) or "material" not in defaults or "thickness" not in defaults:
        fail('"defaults" needs a material and a thickness.')
    if defaults["material"] not in names:
        fail(f'the default material "{defaults["material"]}" is not in the materials list.')
    default_t = number(defaults["thickness"], "the default thickness", strict=True)
    if default_t not in names[defaults["material"]]:
        fail(f'the default thickness {default_t:g} is not an allowed thickness of "{defaults["material"]}".')

    limits = data.get("limits")
    if not isinstance(limits, dict):
        fail('"limits" is missing.')
    for key in LIMIT_KEYS:
        row = limits.get(key)
        if not isinstance(row, dict):
            fail(f'the limit "{key}" is missing.')
        number(row.get("mm", 0), f"{key}: mm")
        number(row.get("times_thickness", 0), f"{key}: times_thickness")
    number(data.get("flat_length_tolerance_mm", 0.1), "flat_length_tolerance_mm")


def resolve(part: Part, rules: Rules) -> Part:
    """Fill in what the rules table supplies: canonical material name and, for an
    L-bracket whose drawing shows no bend radius, the default radius."""
    resolved = part.model_copy(deep=True)
    resolved.name = resolved.name.strip()
    resolved.material = rules.canonical_material(resolved.material)
    if resolved.is_bracket:
        if resolved.bend_radius is None:
            bend = rules.bend_data(resolved.material, resolved.thickness)
            if bend:
                resolved.bend_radius = bend.bend_radius
    else:
        resolved.flange_b = None
        resolved.bend_radius = None
        for hole in resolved.holes:
            hole.flange = "A"
    return resolved


def check(part: Part, rules: Rules) -> list[Issue]:
    """Check a resolved part. Returns an empty list when everything is fine."""
    issues: list[Issue] = []

    def error(field: str | None, message: str) -> None:
        issues.append(Issue(severity="error", field=field, message=message))

    def rule(field: str | None, message: str) -> None:
        issues.append(Issue(severity="rule", field=field, message=message))

    bracket = part.is_bracket
    t = part.thickness
    len_name = "Flange A" if bracket else "Length"

    # --- Basic values -------------------------------------------------------
    for field, label, value in [
        ("thickness", "Thickness", t),
        ("width", "Width", part.width),
        ("flange_a", len_name, part.flange_a),
    ]:
        if value is None or value <= 0:
            error(field, f"{label} must be greater than 0.")
    if bracket and (part.flange_b is None or part.flange_b <= 0):
        error("flange_b", "Flange B is missing. An L-bracket needs both flange lengths.")
    if any(i.severity == "error" for i in issues):
        return issues

    # --- Material and thickness ----------------------------------------------
    material = rules.find_material(part.material)
    bend = None
    if not material:
        error(
            "material",
            f'Material "{part.material or "(empty)"}" is not in the rules table. '
            f"Choose one of: {', '.join(rules.material_names())}.",
        )
    else:
        bend = rules.bend_data(part.material, t)
        if bend is None:
            allowed = ", ".join(fmt(x) for x in rules.thicknesses(part.material))
            error(
                "thickness",
                f"Thickness {fmt(t)} mm is not allowed for {material['name']}. Allowed: {allowed} mm.",
            )

    # --- Bend ----------------------------------------------------------------
    r = 0.0
    if bracket:
        if part.bend_radius is None:
            error("bend_radius", "Inner bend radius is missing and the rules table has no default for it.")
            return issues
        r = part.bend_radius
        if r <= 0:
            error("bend_radius", "Inner bend radius must be greater than 0.")
            return issues
        if bend and abs(r - bend.bend_radius) > 1e-6:
            rule(
                "bend_radius",
                f"Inner bend radius {fmt(r)} mm differs from the rules table value "
                f"({fmt(bend.bend_radius)} mm for {part.material}, {fmt(t)} mm).",
            )
        for field, label, length in [("flange_a", "Flange A", part.flange_a), ("flange_b", "Flange B", part.flange_b)]:
            if length <= r + t:
                error(
                    field,
                    f"{label} ({fmt(length)} mm) is too short to bend: it must be longer than "
                    f"bend radius + thickness ({fmt(r + t)} mm).",
                )
        if any(i.severity == "error" and i.field in ("flange_a", "flange_b") for i in issues):
            return issues

    # --- Holes ---------------------------------------------------------------
    min_dia = rules.limit("min_hole_diameter", t)
    min_edge = rules.limit("min_hole_edge_to_part_edge", t)
    min_bend = rules.limit("min_hole_edge_to_bend", t)
    min_gap = rules.limit("min_hole_edge_to_hole_edge", t)

    for i, hole in enumerate(part.holes):
        n = i + 1
        base = f"holes.{i}"
        if hole.diameter <= 0:
            error(f"{base}.diameter", f"Hole {n}: diameter must be greater than 0.")
            continue
        if bracket and hole.flange == "B":
            flange_len, flange_label = part.flange_b, "Flange B"
        else:
            flange_len, flange_label = part.flange_a, len_name
        radius = hole.diameter / 2
        edge_name = "the free edge" if bracket else "the bottom edge"
        far_name = "the right side"
        # On a plate the hole sits in length x width; on a bracket in width x flange.
        along_left_extent = part.flange_a if not bracket else part.width
        along_edge_extent = part.width if not bracket else flange_len - (r + t)

        if hole.diameter < min_dia - 1e-9:
            rule(f"{base}.diameter", f"Hole {n} (Ø{fmt(hole.diameter)}) is smaller than the minimum hole diameter of {fmt(min_dia)} mm.")

        outside = False
        if hole.from_left - radius < 0 or hole.from_left + radius > along_left_extent:
            error(f"{base}.from_left", f"Hole {n} does not fit on the part: it runs off the left or right side.")
            outside = True
        if hole.from_edge - radius < 0:
            error(f"{base}.from_edge", f"Hole {n} does not fit on the part: it runs off {edge_name}.")
            outside = True
        elif hole.from_edge + radius > along_edge_extent:
            if bracket:
                error(f"{base}.from_edge", f"Hole {n} runs into the bend of {flange_label}. Move it towards the free edge.")
            else:
                error(f"{base}.from_edge", f"Hole {n} does not fit on the part: it runs off the top edge.")
            outside = True
        if outside:
            continue

        gaps = [
            (hole.from_left - radius, "the left side", f"{base}.from_left"),
            (along_left_extent - hole.from_left - radius, far_name, f"{base}.from_left"),
            (hole.from_edge - radius, edge_name, f"{base}.from_edge"),
        ]
        if not bracket:
            gaps.append((along_edge_extent - hole.from_edge - radius, "the top edge", f"{base}.from_edge"))
        for gap, what, field in gaps:
            if gap < min_edge - 1e-9:
                rule(field, f"Hole {n} is too close to {what}: {fmt(gap)} mm, minimum {fmt(min_edge)} mm.")
        if bracket:
            gap = along_edge_extent - hole.from_edge - radius
            if gap < min_bend - 1e-9:
                rule(f"{base}.from_edge", f"Hole {n} is too close to the bend: {fmt(gap)} mm, minimum {fmt(min_bend)} mm.")

    for i, a in enumerate(part.holes):
        for j in range(i + 1, len(part.holes)):
            b = part.holes[j]
            if (bracket and a.flange != b.flange) or a.diameter <= 0 or b.diameter <= 0:
                continue
            centre = ((a.from_left - b.from_left) ** 2 + (a.from_edge - b.from_edge) ** 2) ** 0.5
            gap = centre - (a.diameter + b.diameter) / 2
            if gap <= 0:
                error(f"holes.{j}.from_left", f"Hole {i + 1} and Hole {j + 1} overlap.")
            elif gap < min_gap - 1e-9:
                rule(f"holes.{j}.from_left", f"Hole {i + 1} and Hole {j + 1} are too close together: {fmt(gap)} mm, minimum {fmt(min_gap)} mm.")

    return issues
