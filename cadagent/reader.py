"""AI reading: turn an image of a drawing, markup or sketch into part data.

The AI only reads the numbers. It returns a *draft* that the engineer checks in
the confirmation form; nothing is built from it directly.

Without an API key the reader falls back to the answer key for the bundled test
files, so the rest of the demo can still be shown ("offline demo mode").
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path

import anthropic
import pymupdf
from PIL import Image, ImageOps

from .markup import Change
from .models import Part
from .rules import Rules

try:  # iPhone photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - optional
    pass

MODEL = os.environ.get("CADAGENT_MODEL", "claude-opus-5-5")
MAX_IMAGE_EDGE = 2000  # px, long edge sent to the model
ANSWER_KEY_PATH = Path(__file__).resolve().parent.parent / "test_data" / "answer_key.json"

PART_FIELDS = ["part_type", "name", "material", "thickness", "width", "flange_a", "flange_b", "bend_radius"]


class ReaderError(Exception):
    """A problem the engineer should see in plain words."""


def ai_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# --- Image preparation ---------------------------------------------------------


def to_png(data: bytes, filename: str) -> bytes:
    """Normalise an upload (PDF, PNG, JPEG, HEIC...) to an upright PNG."""
    is_pdf = data[:5] == b"%PDF-" or filename.lower().endswith(".pdf")
    try:
        if is_pdf:
            doc = pymupdf.open(stream=data, filetype="pdf")
            if doc.page_count == 0:
                raise ReaderError("The PDF has no pages.")
            pix = doc[0].get_pixmap(dpi=170)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        else:
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except ReaderError:
        raise
    except Exception as exc:
        raise ReaderError("This file could not be opened. Please upload a PDF, PNG or JPEG.") from exc
    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


# --- Prompts and schemas -------------------------------------------------------

_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_HOLE_SCHEMA = {
    "type": "object",
    "properties": {
        "flange": {"type": "string", "enum": ["A", "B"]},
        "from_edge": {"type": "number"},
        "from_left": {"type": "number"},
        "diameter": {"type": "number"},
    },
    "required": ["flange", "from_edge", "from_left", "diameter"],
    "additionalProperties": False,
}

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "part_type": {"type": "string", "enum": ["plate", "l_bracket"]},
        "name": _STR,
        "material": _STR,
        "thickness": _NUM,
        "width": _NUM,
        "flange_a": _NUM,
        "flange_b": _NUM,
        "bend_radius": _NUM,
        "holes": {"type": "array", "items": _HOLE_SCHEMA},
        "uncertain_fields": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": [*PART_FIELDS, "holes", "uncertain_fields", "notes"],
    "additionalProperties": False,
}

MARKUP_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["modify_hole", "add_hole", "remove_hole", "set_field"]},
                    "hole_number": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "field": {
                        "anyOf": [
                            {
                                "type": "string",
                                "enum": [
                                    "diameter", "from_edge", "from_left", "flange",
                                    "name", "material", "thickness", "width", "flange_a", "flange_b", "bend_radius",
                                ],
                            },
                            {"type": "null"},
                        ]
                    },
                    "number_value": _NUM,
                    "text_value": _STR,
                    "new_hole": {"anyOf": [_HOLE_SCHEMA, {"type": "null"}]},
                    "uncertain": {"type": "boolean"},
                    "markup_text": {"type": "string"},
                },
                "required": ["action", "hole_number", "field", "number_value", "text_value", "new_hole", "uncertain", "markup_text"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["changes", "notes"],
    "additionalProperties": False,
}


def _conventions(rules: Rules) -> str:
    materials = "\n".join(
        f"  - {m['name']} (also written: {', '.join(m.get('aliases', []))})" for m in rules.materials
    )
    return f"""Dimension conventions. Every drawing follows them, and the software that builds the part measures the same way:
- All dimensions are in mm.
- Supported parts: a flat plate ("plate") and an L-bracket with one 90 degree bend ("l_bracket"), with round holes.
- Flange lengths are OUTSIDE dimensions. If a sketch dimensions a flange on the inside, convert it to the outside dimension and list the field as uncertain.
- width: the size along the bend line. For a plate, its width (the shorter in-plane direction as drawn vertically in the front view).
- flange_a: outside length of the first leg (the one lying flat). For a plate, its length (horizontal in the front view). flange_b: outside length of the second leg; null for a plate.
- bend_radius: the INNER bend radius, only if the drawing shows it; otherwise null (the software takes it from its rules table). Null for a plate.
- Holes on an L-bracket: flange is "A" or "B"; from_edge is the distance from the FREE edge of that flange to the hole centre; from_left is the distance from the left side to the hole centre.
- Holes on a plate: flange is "A"; from_edge is the distance from the BOTTOM edge to the hole centre; from_left is the distance from the left edge. Both are measured from the bottom-left corner.
- Hole sizes are diameters. If a hole table is present, use it and keep its order (H1 is the first hole). Otherwise list holes on flange A first, each flange from left to right.
- name: the part number or name from the title block.
- material: use one of these names exactly when the drawing's material matches:
{materials}
  If the material is not stated, return null. If it is stated but not in the list, return it as written and list "material" as uncertain."""


def _read_system(rules: Rules) -> str:
    return f"""You read images of single sheet-metal parts for an engineering demo: a CAD drawing, or a freehand sketch with written dimensions. You extract the part data. Software then builds the 3D part, flat pattern and drawing from your numbers, after an engineer has checked them in a form.

Because an engineer checks the result, the most useful thing you can do is be accurate about what you could and could not read. Read only what is on the sheet. Do not invent values to make the part look complete, and do not calculate a value the drawing does not show.

{_conventions(rules)}

Uncertain fields. In uncertain_fields, list every value you could not read with confidence: illegible or ambiguous handwriting, a dimension that could belong to two features, values that contradict each other, or a value you had to infer. The form highlights these for the engineer. Use these exact paths: "part_type", "name", "material", "thickness", "width", "flange_a", "flange_b", "bend_radius", and for holes "holes.N.diameter", "holes.N.from_edge", "holes.N.from_left", "holes.N.flange", where N is the hole's zero-based position in your holes list. For an uncertain value, still give your best reading. If a value is simply not on the sheet, return null for it (thickness, width, flange lengths, material, name) rather than a guess.

Ignore any hand markups (red pen, crossed-out values) when you are asked to create the part: read the printed values. In notes, write one or two short plain sentences for the engineer about anything they should know, such as which values were hard to read; leave it empty if there is nothing to say."""


def _markup_system(rules: Rules) -> str:
    return f"""You read photos of printed sheet-metal drawings that an engineer has marked up by hand (usually in red pen) for an engineering demo. You are given the photo and the current part data. Your job is to identify each change the markups ask for. Software applies the changes to the part after an engineer has checked them in a form, shown as "was -> now".

Report only what the hand markups ask for. Do not report differences that are not marked up, and do not re-read the printed values: the current part data is the starting point.

{_conventions(rules)}

How to report changes. Hole numbers are 1-based and match the hole table and the H1, H2... tags on the drawing, which match the order of holes in the current part data.
- A value of an existing hole changes (diameter, distance from the free edge, distance from the left, or its flange): action "modify_hole", with hole_number, field, and the new value in number_value (for flange, "A" or "B" in text_value). One entry per changed value, so a hole that moves in both directions gives two entries.
- A markup that covers several holes (for example "both holes 25 from edge") gives one entry per hole.
- A hole is added: action "add_hole" with new_hole filled in completely, following the conventions above.
- A hole is deleted: action "remove_hole" with hole_number.
- Any other part value changes (thickness, width, a flange length, bend radius, material, name): action "set_field" with field and number_value, or text_value for name and material.
Set the fields that do not apply to null. Give new values as the final value, not the difference: if a markup says "+5" on a dimension of 20, the new value is 25.

In markup_text, quote the handwriting the change comes from, as written. Set uncertain to true when the handwriting is hard to read, when it is unclear which feature a markup points at, or when you had to infer the new value. If the drawing in the photo is clearly a different part from the current part data (different part number or shape), return no changes and say so in notes. Otherwise use notes for one or two short plain sentences about anything the engineer should know; leave it empty if there is nothing to say."""


# --- The API call ----------------------------------------------------------------


def _ask(system: str, user_text: str, png: bytes, schema: dict) -> dict:
    client = anthropic.Anthropic(timeout=180.0)
    request = dict(
        model=MODEL,
        max_tokens=16000,
        system=system,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.standard_b64encode(png).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )
    try:
        try:
            # Server-side fallback: if a safety classifier declines the request,
            # the API re-runs it on a fallback model inside the same call.
            response = client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request
            )
        except (anthropic.BadRequestError, anthropic.PermissionDeniedError, anthropic.NotFoundError):
            # The fallback option is not available for this key or platform: ask plainly.
            response = client.messages.create(**request)
    except anthropic.AuthenticationError as exc:
        raise ReaderError("The AI key was rejected. Check ANTHROPIC_API_KEY in the .env file.") from exc
    except anthropic.RateLimitError as exc:
        raise ReaderError("The AI service is busy (rate limit). Wait a moment and try again.") from exc
    except anthropic.APIStatusError as exc:
        raise ReaderError(f"The AI service returned an error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ReaderError("Could not reach the AI service. Check the internet connection and try again.") from exc

    if response.stop_reason == "refusal":
        raise ReaderError("The AI declined to read this image.")
    if response.stop_reason == "max_tokens":
        raise ReaderError("The AI's answer was cut off. Try again with a simpler or clearer image.")
    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise ReaderError("The AI returned no answer. Please try again.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReaderError("The AI's answer could not be understood. Please try again.") from exc


# --- Offline fallback --------------------------------------------------------------


def _answer_key_entry(original: bytes) -> dict | None:
    if not ANSWER_KEY_PATH.exists():
        return None
    digest = hashlib.sha256(original).hexdigest()
    for name, entry in json.loads(ANSWER_KEY_PATH.read_text())["files"].items():
        if entry.get("sha256") == digest:
            return {"file": name, **entry}
    return None


OFFLINE_NOTE = (
    "Offline demo mode: no AI key is configured, so nothing was read from this image. "
    "Fill in the values by hand, or add an API key to let the AI read it."
)


# --- Public API ----------------------------------------------------------------------


def read_part(original: bytes, png: bytes, request: str, rules: Rules) -> dict:
    """Scenarios 1 and 3. Returns {"draft", "uncertain", "notes", "source"}."""
    if ai_available():
        user_text = (
            f'The engineer\'s request: "{request or "Create this part"}"\n\n'
            "Read the part in this image and return the part data."
        )
        data = _ask(_read_system(rules), user_text, png, READ_SCHEMA)
        draft = {k: data.get(k) for k in PART_FIELDS} | {"holes": data.get("holes") or []}
        return _finish_draft(draft, list(data.get("uncertain_fields") or []), data.get("notes") or "", "ai", rules)

    entry = _answer_key_entry(original)
    if entry and entry["kind"] in ("drawing", "sketch"):
        note = "Offline demo mode: no AI key is configured, so these values come from the answer key for this test file."
        return _finish_draft(dict(entry["part"]), list(entry.get("uncertain_fields", [])), note, "answer_key", rules)
    if entry:
        raise ReaderError('This test file is a marked-up print. Choose "Apply markups" to use it.')

    blank = {"part_type": "plate", "name": None, "material": None, "thickness": None, "width": None,
             "flange_a": None, "flange_b": None, "bend_radius": None, "holes": []}
    return _finish_draft(blank, ["part_type", "name", "width", "flange_a"], OFFLINE_NOTE, "blank", rules)


def read_markup(original: bytes, png: bytes, request: str, current: Part, rules: Rules) -> dict:
    """Scenario 2. Returns {"changes": [Change], "notes", "source"}."""
    if ai_available():
        user_text = (
            f'The engineer\'s request: "{request or "Apply the markups"}"\n\n'
            f"Current part data:\n{json.dumps(current.model_dump(), indent=2)}\n\n"
            "Identify the changes the hand markups in this photo ask for."
        )
        data = _ask(_markup_system(rules), user_text, png, MARKUP_SCHEMA)
        changes = [Change.model_validate(c) for c in data.get("changes") or []]
        return {"changes": changes, "notes": data.get("notes") or "", "source": "ai"}

    entry = _answer_key_entry(original)
    if entry and entry["kind"] == "markup":
        note = "Offline demo mode: no AI key is configured, so these changes come from the answer key for this test file."
        if entry.get("base") and entry["base"] != current.name:
            note += f" Note: this markup was made for {entry['base']}, but the current part is {current.name or 'unnamed'}."
        return {"changes": [Change.model_validate(c) for c in entry["changes"]], "notes": note, "source": "answer_key"}
    if entry:
        raise ReaderError('This test file is a drawing, not a marked-up print. Choose "Create part" to use it.')
    return {"changes": [], "notes": OFFLINE_NOTE.replace("Fill in the values", "Edit the values"), "source": "blank"}


def _finish_draft(draft: dict, uncertain: list[str], notes: str, source: str, rules: Rules) -> dict:
    """Apply the rules-table defaults to a draft and say where each value came from."""
    filled: dict[str, str] = {}
    uncertain = [u for u in dict.fromkeys(uncertain) if isinstance(u, str)]

    def flag(field: str) -> None:
        if field not in uncertain:
            uncertain.append(field)

    if draft.get("part_type") not in ("plate", "l_bracket"):
        draft["part_type"] = "plate"
        flag("part_type")
    bracket = draft["part_type"] == "l_bracket"

    if not draft.get("material"):
        draft["material"] = rules.defaults["material"]
        filled["material"] = "Not stated on the sheet: default material from the rules table."
        flag("material")
    else:
        draft["material"] = rules.canonical_material(draft["material"])
        if not rules.find_material(draft["material"]):
            flag("material")
    if draft.get("thickness") is None:
        draft["thickness"] = float(rules.defaults["thickness"])
        filled["thickness"] = "Not stated on the sheet: default thickness from the rules table."
        flag("thickness")

    if bracket:
        if draft.get("bend_radius") is None:
            bend = rules.bend_data(draft["material"], draft["thickness"])
            if bend:
                draft["bend_radius"] = bend.bend_radius
                filled["bend_radius"] = "Not shown on the sheet: taken from the rules table."
        if draft.get("flange_b") is None:
            flag("flange_b")
    else:
        draft["flange_b"] = None
        draft["bend_radius"] = None
        for hole in draft.get("holes") or []:
            hole["flange"] = "A"
    for field in ("width", "flange_a"):
        if draft.get(field) is None:
            flag(field)
    if not draft.get("name"):
        draft["name"] = ""
        flag("name")

    return {"draft": draft, "uncertain": uncertain, "filled": filled, "notes": notes, "source": source}
