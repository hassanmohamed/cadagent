import json
import math

import cadquery as cq
import ezdxf
import pymupdf
import pytest

from cadagent.builder import build_all
from cadagent.geometry import build_solid, expected_volume
from cadagent.rules import resolve


def test_bracket_solid(bracket):
    shape = build_solid(bracket).val()
    box = shape.BoundingBox()
    assert shape.isValid()
    assert (box.xlen, box.ylen, box.zlen) == pytest.approx((60, 80, 50), abs=1e-6)  # outside dimensions
    assert shape.Volume() == pytest.approx(expected_volume(bracket), rel=1e-9)
    assert len(shape.Solids()) == 1


def test_plate_solid(plate):
    shape = build_solid(plate).val()
    box = shape.BoundingBox()
    assert (box.xlen, box.ylen, box.zlen) == pytest.approx((120, 80, 3), abs=1e-6)
    assert shape.Volume() == pytest.approx(120 * 80 * 3 - math.pi * (4.5**2 + 10**2) * 3, rel=1e-9)


def test_hole_positions_in_3d(bracket):
    """A probe through each hole must not hit material."""
    solid = build_solid(bracket)
    a_hole = cq.Workplane("XY").workplane(offset=-1).center(15, 20).circle(4.4).extrude(5)
    b_hole = cq.Workplane("XZ").workplane(offset=-81).center(30, 50 - 20).circle(5.4).extrude(5)
    assert solid.intersect(a_hole).val().Volume() == pytest.approx(0, abs=1e-6)
    assert solid.intersect(b_hole).val().Volume() == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("fixture", ["bracket", "plate"])
def test_build_all_outputs(fixture, request, rules, tmp_path):
    part = resolve(request.getfixturevalue(fixture), rules)
    summary = build_all(part, rules, tmp_path)
    files = summary["files"]

    # STEP: re-import and compare with the part data
    step = cq.importers.importStep(str(tmp_path / files["step"])).val()
    assert step.Volume() == pytest.approx(expected_volume(part), rel=1e-6)

    # DXF: outline, one circle per hole, bend line, millimetres
    doc = ezdxf.readfile(tmp_path / files["dxf"])
    assert not doc.audit().has_errors
    msp = doc.modelspace()
    assert doc.units == ezdxf.units.MM
    circles = msp.query('CIRCLE[layer=="HOLES"]')
    assert len(circles) == len(part.holes)
    assert sorted(round(c.dxf.radius * 2, 6) for c in circles) == sorted(h.diameter for h in part.holes)
    outline = msp.query('LWPOLYLINE[layer=="OUTLINE"]').first
    xs, ys = zip(*[(p[0], p[1]) for p in outline.get_points()])
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx(tuple(summary["derived"]["flat_size_mm"]), abs=1e-3)
    assert len(msp.query('LINE[layer=="BEND"]')) == (1 if part.is_bracket else 0)
    assert len(msp.query("DIMENSION")) >= 2

    # PDF: one page with the views, title block and parts list
    pdf = pymupdf.open(tmp_path / files["pdf"])
    text = pdf[0].get_text()
    assert pdf.page_count == 1
    for expected in [part.name, "FRONT VIEW", "SIDE VIEW", "FLAT PATTERN", "HOLE TABLE", "PART NO.", part.material]:
        assert expected in text

    # JSON: the numbers behind the part
    data = json.loads((tmp_path / files["json"]).read_text())
    assert data["part"] == part.model_dump()
    assert data["units"] == "mm"

    mesh = json.loads((tmp_path / "mesh.json").read_text())
    assert len(mesh["positions"]) % 3 == 0 and max(mesh["indices"]) < len(mesh["positions"]) // 3
    assert (tmp_path / "flat.svg").read_text().startswith("<svg")
