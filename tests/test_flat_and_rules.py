import math

import pytest

from cadagent.flat import flat_length, unfold
from cadagent.models import Hole, Part
from cadagent.rules import check, resolve


def test_flat_length_formula():
    # L = A + B - 2(r + t) + (pi / 2)(r + k t), worked by hand
    assert flat_length(80, 50, 3, 3, 0.44) == pytest.approx(80 + 50 - 12 + (math.pi / 2) * (3 + 1.32))
    assert flat_length(80, 50, 3, 3, 0.44) == pytest.approx(124.7858, abs=1e-4)
    # k = 0.5 puts the neutral axis mid-thickness
    assert flat_length(100, 100, 2, 2, 0.5) == pytest.approx(200 - 8 + (math.pi / 2) * 3)


def test_unfold_bracket(bracket, rules):
    flat = unfold(bracket, rules)
    assert flat.size_x == 60
    assert flat.flat_length == pytest.approx(124.7858, abs=1e-4)
    assert flat.leg_a_flat == 74 and flat.leg_b_flat == 44
    assert flat.leg_a_flat + flat.bend_allowance + flat.leg_b_flat == pytest.approx(flat.flat_length)
    assert flat.bend_line_y == pytest.approx(74 + flat.bend_allowance / 2)
    h1, _, h3 = flat.holes
    assert (h1.x, h1.y) == (15, 20)  # flange A: measured from its free edge
    assert (h3.x, h3.y) == (30, pytest.approx(flat.flat_length - 20))  # flange B: from the far end


def test_unfold_plate(plate, rules):
    flat = unfold(plate, rules)
    assert (flat.size_x, flat.size_y, flat.flat_length) == (120, 80, 120)
    assert flat.bend_line_y is None
    assert (flat.holes[0].x, flat.holes[0].y) == (15, 15)


def test_answer_key_flat_lengths(answer_key, rules):
    for name, entry in answer_key.items():
        part = Part.model_validate(entry.get("expected_part") or entry["part"])
        got = unfold(resolve(part, rules), rules).flat_length
        assert abs(got - entry["expected_flat_length"]) <= rules.flat_length_tolerance, name


def test_good_parts_pass(bracket, plate, rules):
    assert check(resolve(bracket, rules), rules) == []
    assert check(resolve(plate, rules), rules) == []


def test_resolve_fills_radius_and_material_alias(bracket, rules):
    bracket.bend_radius = None
    bracket.material = "s235"
    resolved = resolve(bracket, rules)
    assert resolved.material == "Steel S235" and resolved.bend_radius == 3


def messages(part, rules):
    return [(i.severity, i.message) for i in check(resolve(part, rules), rules)]


def test_hole_too_close_to_bend(bracket, rules):
    bracket.holes[0].from_edge = 68  # flat leg is 74; hole edge 72.5 -> 1.5 mm from the bend
    found = messages(bracket, rules)
    assert ("rule", "Hole 1 is too close to the bend: 1.5 mm, minimum 6 mm.") in found


def test_hole_in_bend_is_an_error(bracket, rules):
    bracket.holes[0].from_edge = 73
    assert any(s == "error" and "runs into the bend" in m for s, m in messages(bracket, rules))


def test_hole_too_close_to_edge(plate, rules):
    plate.holes[0].from_left = 6  # hole edge 1.5 mm from the left side
    assert ("rule", "Hole 1 is too close to the left side: 1.5 mm, minimum 4.5 mm.") in messages(plate, rules)


def test_hole_off_the_part(plate, rules):
    plate.holes[0].from_edge = 79
    assert any(s == "error" and "runs off the top edge" in m for s, m in messages(plate, rules))


def test_small_hole_and_overlap(plate, rules):
    plate.holes.append(Hole(from_edge=40, from_left=65, diameter=2))
    found = messages(plate, rules)
    assert any(s == "rule" and "smaller than the minimum hole diameter" in m for s, m in found)
    assert ("error", "Hole 2 and Hole 3 overlap.") in found


def test_material_and_thickness(plate, rules):
    plate.thickness = 7
    assert any("Thickness 7 mm is not allowed for Steel S235" in m for _, m in messages(plate, rules))
    plate.material = "Titanium"
    assert any('Material "Titanium" is not in the rules table' in m for _, m in messages(plate, rules))


def test_bracket_needs_flange_b_and_long_enough_flanges(bracket, rules):
    bracket.flange_b = None
    assert any("Flange B is missing" in m for _, m in messages(bracket, rules))
    bracket.flange_b = 5
    assert any("too short to bend" in m for _, m in messages(bracket, rules))


def test_nonstandard_radius_is_flagged(bracket, rules):
    bracket.bend_radius = 5
    assert any(s == "rule" and "differs from the rules table" in m for s, m in messages(bracket, rules))


def test_broken_rules_file_is_explained(tmp_path):
    import copy

    import yaml

    from cadagent.rules import RULES_PATH, Rules, RulesError

    good = yaml.safe_load(RULES_PATH.read_text())

    def message(change) -> str:
        data = copy.deepcopy(good)
        change(data)
        with pytest.raises(RulesError) as caught:
            Rules(data)
        return str(caught.value)

    assert "k_factor must be between 0 and 1" in message(lambda d: d["materials"][0]["thicknesses"][3].update(k_factor=44))
    assert "bend_radius must be a number" in message(lambda d: d["materials"][0]["thicknesses"][3].update(bend_radius="3mm"))
    assert 'default material "Brass"' in message(lambda d: d["defaults"].update(material="Brass"))
    assert "default thickness 7" in message(lambda d: d["defaults"].update(thickness=7))
    assert '"min_hole_edge_to_bend" is missing' in message(lambda d: d["limits"].pop("min_hole_edge_to_bend"))

    bad = tmp_path / "rules.yaml"
    bad.write_text("materials:\n  - name: X\n   thicknesses: [")
    with pytest.raises(RulesError, match="could not be read"):
        Rules.load(bad)
    with pytest.raises(RulesError, match="missing"):
        Rules.load(tmp_path / "nope.yaml")
