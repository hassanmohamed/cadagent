"""Build every output for a confirmed part.

Outputs written to the version folder:
    <name>.step          the 3D model
    <name>_flat.dxf      flat pattern for laser cutting
    <name>_drawing.pdf   drawing sheet
    <name>.json          part data, the link to future CAD integration
plus mesh.json, flat.svg and sheet.png (a preview of the PDF) for the web page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf

from .dxf_export import export_dxf, flat_svg
from .flat import unfold
from .geometry import build_solid, expected_volume, export_step, mesh
from .models import Part
from .rules import Rules
from .sheet import render_sheet

SCHEMA_VERSION = "1.0"


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._")
    return cleaned or "part"


def build_all(part: Part, rules: Rules, out_dir: Path) -> dict:
    """Build all outputs for a resolved, checked part. Returns a summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_name(part.name)

    flat = unfold(part, rules)
    solid = build_solid(part)
    volume = solid.val().Volume()
    if abs(volume - expected_volume(part)) > max(1e-3, 1e-6 * volume):
        raise RuntimeError("The 3D model does not match the part data (volume check failed).")

    files = {
        "step": f"{stem}.step",
        "dxf": f"{stem}_flat.dxf",
        "pdf": f"{stem}_drawing.pdf",
        "json": f"{stem}.json",
    }
    export_step(solid, out_dir / files["step"])
    export_dxf(part, flat, out_dir / files["dxf"])
    render_sheet(part, flat, out_dir / files["pdf"])

    derived = {
        "flat_length_mm": round(flat.flat_length, 3),
        "flat_size_mm": [round(flat.size_x, 3), round(flat.size_y, 3)],
        "volume_mm3": round(volume, 2),
    }
    if part.is_bracket:
        derived |= {
            "bend_angle_deg": 90,
            "k_factor": flat.k_factor,
            "bend_allowance_mm": round(flat.bend_allowance, 3),
            "bend_line_from_flange_a_edge_mm": round(flat.bend_line_y, 3),
        }
    part_json = {
        "schema_version": SCHEMA_VERSION,
        "units": "mm",
        "part": part.model_dump(),
        "derived": derived,
        "rules_version": rules.version,
    }
    (out_dir / files["json"]).write_text(json.dumps(part_json, indent=2))
    (out_dir / "mesh.json").write_text(json.dumps(mesh(solid)))
    (out_dir / "flat.svg").write_text(flat_svg(part, flat))
    with pymupdf.open(out_dir / files["pdf"]) as pdf:
        pdf[0].get_pixmap(dpi=150).save(out_dir / "sheet.png")

    return {"files": files, "derived": derived, "part_json": part_json}
