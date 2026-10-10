"""The Streamlit app, driven headlessly in offline demo mode."""

import pytest
from streamlit.testing.v1 import AppTest

from .conftest import ROOT


@pytest.fixture
def app(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "APP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def read_sample(at, label):
    at.selectbox(key="sample").select(label).run()
    button(at, "Read").click().run()
    assert not at.exception and not at.error
    return at


def build(at):
    button(at, "Apply and build").click().run()
    assert not at.exception and not at.error
    return at.session_state.session


def test_starts_empty_in_offline_mode(app):
    assert any("Offline demo mode" in w.value for w in app.sidebar.warning)
    assert button(app, "Read").disabled
    assert button(app, "↶ Undo").disabled
    assert app.session_state.session.current is None


def test_scenario_1_then_2_then_undo(app, answer_key):
    read_sample(app, "L-bracket drawing")
    assert app.session_state.mode == "Create part"
    assert app.session_state.draft == answer_key["drawings/BRK-001.pdf"]["part"]
    assert any("All engineering rules pass" in s.value for s in app.success)
    session = build(app)
    assert session.current.summary["derived"]["flat_length_mm"] == pytest.approx(124.79, abs=0.01)
    assert app.session_state.view == "3D view"

    read_sample(app, "L-bracket markup")
    assert app.session_state.mode == "Apply markups"  # picking a markup file switches the mode
    text = " ".join(m.value for m in app.markdown)
    assert "Hole 3: Ø11 → Ø14" in text and "Hole 4: added" in text
    session = build(app)
    assert session.current.part.model_dump() == answer_key["markups/BRK-001_markup.jpg"]["expected_part"]
    assert len(session.versions) == 2

    button(app, "↶ Undo").click().run()
    assert len(session.versions) == 1 and len(session.current.part.holes) == 3
    assert app.session_state.draft == answer_key["drawings/BRK-001.pdf"]["part"]


def test_scenario_3_sketch_flags_uncertain_value(app):
    read_sample(app, "Hand sketch")
    labels = [n.label for n in app.number_input]
    assert "Flange B (mm, outside) ⚠️ check" in labels
    app.number_input(key=f"flange_b_{app.session_state.gen}").set_value(41.0).run()
    assert "Flange B (mm, outside)" in [n.label for n in app.number_input]  # edited: no longer flagged
    assert build(app).current.part.flange_b == 41


def test_rule_violation_blocks_and_can_be_overridden(app):
    read_sample(app, "L-bracket drawing")
    app.number_input(key=f"flange_a_{app.session_state.gen}").set_value(31.0).run()
    assert any("too close to the bend" in w.value for w in app.warning)
    assert button(app, "Apply and build").disabled
    button(app, "Build anyway").click().run()
    session = app.session_state.session
    assert session.current.part.flange_a == 31 and "rules overridden" in session.current.how


def test_impossible_part_cannot_be_built(app):
    read_sample(app, "Plate drawing")
    app.number_input(key=f"width_{app.session_state.gen}").set_value(20.0).run()
    assert any("does not fit on the part" in e.value for e in app.error)
    assert button(app, "Apply and build").disabled
    assert not [b for b in app.button if b.label == "Build anyway"]


def test_markup_before_any_part_is_explained(app):
    app.selectbox(key="sample").select("Plate markup").run()
    assert any("Create the part from its drawing first" in i.value for i in app.info)
    assert button(app, "Read").disabled


def test_new_part_clears_everything(app):
    read_sample(app, "Plate drawing")
    build(app)
    button(app, "New part").click().run()
    assert app.session_state.session.current is None and app.session_state.draft is None


def test_password_gate(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60).run()
    assert "session" not in at.session_state  # nothing behind the gate has run
    at.text_input[0].set_value("wrong")  # a form sends its values together with the click
    at.button[0].click().run()
    assert any("not correct" in e.value for e in at.error) and "session" not in at.session_state
    at.text_input[0].set_value("open-sesame")
    at.button[0].click().run()
    assert "session" in at.session_state
