import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from cadagent import reader
from cadagent.markup import Change, apply_changes
from cadagent.models import Hole, Part

from .conftest import TEST_DATA


def test_answer_key_markups_give_expected_parts(answer_key):
    for name, entry in answer_key.items():
        if entry["kind"] != "markup":
            continue
        base = Part.model_validate(answer_key[f"drawings/{entry['base']}.pdf"]["part"])
        new, applied, problems = apply_changes(base, [Change.model_validate(c) for c in entry["changes"]])
        assert problems == []
        assert new.model_dump() == entry["expected_part"], name
        assert [a.label for a in applied] == entry["expected_changes"]


def test_was_now_labels(bracket):
    new, applied, problems = apply_changes(bracket, [
        Change(action="modify_hole", hole_number=1, field="diameter", number_value=14),
        Change(action="modify_hole", hole_number=2, field="from_edge", number_value=25),
        Change(action="set_field", field="thickness", number_value=4),
        Change(action="add_hole", new_hole=Hole(flange="B", from_edge=10, from_left=12, diameter=6)),
    ])
    assert problems == []
    assert [a.label for a in applied] == [
        "Hole 1: Ø9 → Ø14",
        "Hole 2: from free edge 20 → 25",
        "Thickness: 3 → 4",
        "Hole 4: added — Ø6, Flange B, 10 from free edge, 12 from left",
    ]
    assert new.holes[0].diameter == 14 and new.thickness == 4 and len(new.holes) == 4
    assert bracket.holes[0].diameter == 9  # the original is untouched


def test_remove_hole_renumbers(bracket):
    new, applied, _ = apply_changes(bracket, [
        Change(action="remove_hole", hole_number=1),
        Change(action="modify_hole", hole_number=3, field="diameter", number_value=14),
    ])
    assert [h.diameter for h in new.holes] == [9, 14]
    assert applied[0].paths == ["holes.1.diameter"]  # hole 3 is now the second row of the form
    assert "Hole 1: removed (was Ø9)" in [a.label for a in applied]


def test_markup_for_a_different_part(plate):
    _, applied, problems = apply_changes(plate, [Change(action="modify_hole", hole_number=5, field="diameter", number_value=25)])
    assert applied == [] and "Hole 5" in problems[0] and "2 holes" in problems[0]


def test_to_png_handles_pdf_and_photo():
    for name in ["drawings/BRK-001.pdf", "markups/BRK-001_markup.jpg"]:
        png = reader.to_png((TEST_DATA / name).read_bytes(), name)
        image = Image.open(io.BytesIO(png))
        assert image.format == "PNG" and max(image.size) <= reader.MAX_IMAGE_EDGE and min(image.size) > 800
    with pytest.raises(reader.ReaderError):
        reader.to_png(b"not an image", "x.png")


def test_offline_reads_answer_key(monkeypatch, rules, answer_key):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    data = (TEST_DATA / "sketches/BRK-002_sketch.jpg").read_bytes()
    result = reader.read_part(data, b"", "", rules)
    assert result["source"] == "answer_key"
    assert result["draft"] == answer_key["sketches/BRK-002_sketch.jpg"]["part"]
    assert result["uncertain"] == ["flange_b"]

    blank = reader.read_part(b"some other file", b"", "", rules)
    assert blank["source"] == "blank" and blank["draft"]["material"] == "Steel S235"
    assert {"width", "flange_a", "material", "thickness"} <= set(blank["uncertain"])


class FakeMessages:
    """Stands in for the Anthropic client so the request shape can be checked offline."""

    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=json.dumps(self.payload)),
        ])


def fake_client(monkeypatch, payload):
    fake = FakeMessages(payload)
    client = SimpleNamespace(messages=fake, beta=SimpleNamespace(messages=fake))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(reader.anthropic, "Anthropic", lambda **kw: client)
    return fake


def test_ai_read_request_and_defaults(monkeypatch, rules):
    fake = fake_client(monkeypatch, {
        "part_type": "l_bracket", "name": "X-1", "material": None, "thickness": None, "width": 40,
        "flange_a": 60, "flange_b": 40, "bend_radius": None,
        "holes": [{"flange": "A", "from_edge": 15, "from_left": 10, "diameter": 7}],
        "uncertain_fields": ["holes.0.diameter"], "notes": "The hole size was hard to read.",
    })
    result = reader.read_part(b"raw", b"png-bytes", "Create this part", rules)

    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": reader.READ_SCHEMA}
    assert "thinking" not in call and "temperature" not in call
    image, text = call["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert "Create this part" in text["text"]
    assert "Steel S235" in call["system"] and "OUTSIDE dimensions" in call["system"]

    assert result["source"] == "ai"
    draft = result["draft"]
    assert draft["material"] == "Steel S235" and draft["thickness"] == 3  # defaults from the rules table
    assert draft["bend_radius"] == 3                                      # looked up, not guessed by the AI
    assert set(result["uncertain"]) == {"holes.0.diameter", "material", "thickness"}
    assert set(result["filled"]) == {"material", "thickness", "bend_radius"}


def test_ai_markup_request(monkeypatch, rules, bracket):
    fake = fake_client(monkeypatch, {"notes": "", "changes": [{
        "action": "modify_hole", "hole_number": 3, "field": "diameter", "number_value": 14,
        "text_value": None, "new_hole": None, "uncertain": True, "markup_text": "Ø14",
    }]})
    result = reader.read_markup(b"raw", b"png", "Apply the markups", bracket, rules)
    text = fake.calls[0]["messages"][0]["content"][1]["text"]
    assert '"name": "BRK-001"' in text  # the current part is given to the AI
    assert fake.calls[0]["output_config"]["format"]["schema"] is reader.MARKUP_SCHEMA
    new, applied, _ = apply_changes(bracket, result["changes"])
    assert new.holes[2].diameter == 14 and applied[0].uncertain


def _strict(schema):
    """Structured outputs need every object closed and every property required."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == set(schema["properties"])
        for value in schema.values():
            _strict(value)
    elif isinstance(schema, list):
        for value in schema:
            _strict(value)


def test_schemas_are_strict():
    _strict(reader.READ_SCHEMA)
    _strict(reader.MARKUP_SCHEMA)


def test_ai_call_falls_back_when_the_beta_option_is_refused(monkeypatch, rules):
    import httpx

    payload = {"part_type": "plate", "name": "P", "material": "S235", "thickness": 3, "width": 80,
               "flange_a": 120, "flange_b": None, "bend_radius": None, "holes": [],
               "uncertain_fields": [], "notes": ""}
    plain = FakeMessages(payload)

    class Refusing:
        def create(self, **kwargs):
            response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
            raise reader.anthropic.BadRequestError("unknown beta", response=response, body=None)

    client = SimpleNamespace(messages=plain, beta=SimpleNamespace(messages=Refusing()))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(reader.anthropic, "Anthropic", lambda **kw: client)
    result = reader.read_part(b"raw", b"png", "", rules)
    assert result["draft"]["material"] == "Steel S235" and len(plain.calls) == 1
    assert "fallbacks" not in plain.calls[0] and "betas" not in plain.calls[0]


def test_ai_refusal_and_cut_off_are_explained(monkeypatch, rules):
    for stop_reason, words in [("refusal", "declined"), ("max_tokens", "cut off")]:
        fake = SimpleNamespace(create=lambda stop_reason=stop_reason, **kw: SimpleNamespace(stop_reason=stop_reason, content=[]))
        client = SimpleNamespace(messages=fake, beta=SimpleNamespace(messages=fake))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(reader.anthropic, "Anthropic", lambda **kw: client)
        with pytest.raises(reader.ReaderError, match=words):
            reader.read_part(b"raw", b"png", "", rules)
