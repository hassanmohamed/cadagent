"""End to end through the web API, in offline demo mode (no AI key needed)."""

import pytest
from fastapi.testclient import TestClient

from cadagent import app as app_module
from cadagent.session import Session

from .conftest import TEST_DATA


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(app_module, "state", Session(tmp_path))
    return TestClient(app_module.app)


def read(client, name, mode="create"):
    with open(TEST_DATA / name, "rb") as f:
        return client.post("/api/read", files={"file": (name.split("/")[-1], f)}, data={"mode": mode, "request": ""})


def apply(client, part, **extra):
    return client.post("/api/apply", json={"part": part, **extra})


def scenario(client, drawing, markup, answer_key):
    """Scenario 1 then scenario 2 for one part. Returns the final state."""
    client.post("/api/reset")
    draft = read(client, drawing).json()
    assert draft["draft"] == answer_key[drawing]["part"]
    built = apply(client, draft["draft"]).json()
    assert built["built"] and built["issues"] == []
    assert built["current"]["derived"]["flat_length_mm"] == pytest.approx(answer_key[drawing]["expected_flat_length"], abs=0.01)
    for url in [*built["current"]["downloads"].values(), built["current"]["mesh_url"], built["current"]["flat_svg_url"], built["current"]["sheet_png_url"]]:
        response = client.get(url)
        assert response.status_code == 200 and len(response.content) > 200

    change = read(client, markup, mode="markup").json()
    assert [c["label"] for c in change["changes"]] == answer_key[markup]["expected_changes"]
    assert change["problems"] == [] and change["changed"]
    final = apply(client, change["draft"], how="Markups").json()
    assert final["built"] and final["current"]["part"] == answer_key[markup]["expected_part"]
    assert final["can_undo"] and len(final["history"]) == 2
    return final


def test_scenarios_1_and_2_plate(client, answer_key):
    final = scenario(client, "drawings/PLT-001.pdf", "markups/PLT-001_markup.jpg", answer_key)
    assert final["current"]["part"]["holes"][4]["diameter"] == 25


def test_scenarios_1_and_2_bracket(client, answer_key):
    final = scenario(client, "drawings/BRK-001.pdf", "markups/BRK-001_markup.jpg", answer_key)
    assert len(final["current"]["part"]["holes"]) == 4


def test_scenario_3_sketch(client, answer_key):
    draft = read(client, "sketches/BRK-002_sketch.jpg").json()
    assert draft["uncertain"] == ["flange_b"]
    built = apply(client, draft["draft"]).json()
    assert built["built"]
    assert built["current"]["derived"]["flat_length_mm"] == pytest.approx(96.46, abs=0.01)


def test_undo_steps_back(client, answer_key):
    scenario(client, "drawings/PLT-001.pdf", "markups/PLT-001_markup.jpg", answer_key)
    back = client.post("/api/undo").json()
    assert back["current"]["part"] == answer_key["drawings/PLT-001.pdf"]["part"]
    assert not back["can_undo"]
    assert client.get(back["current"]["downloads"]["step"]).status_code == 200
    assert client.post("/api/undo").status_code == 409


def test_rule_violation_blocks_then_build_anyway(client, answer_key):
    part = dict(answer_key["drawings/BRK-001.pdf"]["part"])
    part["holes"] = [{"flange": "A", "from_edge": 68, "from_left": 15, "diameter": 9}]
    blocked = apply(client, part)
    assert blocked.status_code == 422 and not blocked.json()["built"]
    assert blocked.json()["issues"][0]["message"] == "Hole 1 is too close to the bend: 1.5 mm, minimum 6 mm."
    assert client.get("/api/state").json()["current"] is None  # nothing was built
    forced = apply(client, part, build_anyway=True).json()
    assert forced["built"] and "rules overridden" in forced["history"][0]["how"]


def test_impossible_geometry_cannot_be_forced(client, answer_key):
    part = dict(answer_key["drawings/BRK-001.pdf"]["part"])
    part["holes"] = [{"flange": "A", "from_edge": 78, "from_left": 15, "diameter": 9}]
    assert apply(client, part, build_anyway=True).status_code == 422


def test_blank_values_are_reported_in_plain_words(client):
    part = {"part_type": "plate", "name": "", "material": "Steel S235", "thickness": 3, "width": None,
            "flange_a": 100, "holes": [{"flange": "A", "from_edge": 10, "from_left": None, "diameter": 5}]}
    issues = client.post("/api/check", json={"part": part}).json()["issues"]
    assert {i["message"] for i in issues} == {"Width is missing or not a number.", "Hole 1: distance from left is missing or not a number."}


def test_markup_needs_a_part_and_wrong_mode_is_explained(client):
    assert read(client, "markups/PLT-001_markup.jpg", mode="markup").status_code == 409
    wrong = read(client, "markups/PLT-001_markup.jpg", mode="create")
    assert wrong.status_code == 422 and "Apply markups" in wrong.json()["error"]


def test_bad_upload(client):
    response = client.post("/api/read", files={"file": ("x.png", b"garbage")}, data={"mode": "create"})
    assert response.status_code == 422 and "could not be opened" in response.json()["error"]


def test_demo_runs_five_times_in_a_row(client, answer_key):
    for _ in range(5):
        scenario(client, "drawings/PLT-001.pdf", "markups/PLT-001_markup.jpg", answer_key)
        scenario(client, "drawings/BRK-001.pdf", "markups/BRK-001_markup.jpg", answer_key)
    assert client.get("/api/health").json()["ok"]


def test_zip_has_all_four_outputs(client, answer_key):
    import io
    import zipfile

    built = apply(client, answer_key["drawings/BRK-001.pdf"]["part"]).json()
    response = client.get(built["current"]["zip_url"])
    assert response.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert sorted(names) == ["BRK-001.json", "BRK-001.step", "BRK-001_drawing.pdf", "BRK-001_flat.dxf"]


def test_page_is_served(client):
    assert "AI CAD Agent" in client.get("/").text
    for asset in ["app.js", "style.css", "vendor/three.module.js", "vendor/OrbitControls.js"]:
        assert client.get(f"/{asset}").status_code == 200
