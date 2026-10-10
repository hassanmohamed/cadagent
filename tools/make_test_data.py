"""Generate PLACEHOLDER test material so the demo can run before the domain
expert delivers the real files.

    uv run python tools/make_test_data.py

Writes to test_data/:
    drawings/PLT-001.pdf, drawings/BRK-001.pdf      2 engineering drawings
    markups/PLT-001_markup.jpg, BRK-001_markup.jpg  2 "phone photos" with red-pen markups
    sketches/BRK-002_sketch.jpg                     1 hand sketch
    answer_key.json                                 correct values per file

The output is deterministic (fixed random seed, fixed date). Handwriting uses
macOS system fonts, so regenerate on a Mac.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cadagent.flat import unfold  # noqa: E402
from cadagent.markup import Change, apply_changes  # noqa: E402
from cadagent.models import Hole, Part  # noqa: E402
from cadagent.rules import Rules, check, resolve  # noqa: E402
from cadagent.sheet import PAGE_H, render_sheet  # noqa: E402

OUT = ROOT / "test_data"
DATE = "2026-10-08"
DPI = 150
RED = (196, 30, 36)
INK = (28, 40, 96)
HAND_FONTS = [
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/System/Library/Fonts/Noteworthy.ttc",
    "/System/Library/Fonts/MarkerFelt.ttc",
]


def hand_font(size: int) -> ImageFont.FreeTypeFont:
    for path in HAND_FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("No handwriting font found. Run this script on macOS.")


# --- The parts -------------------------------------------------------------------

PLATE = Part(
    part_type="plate", name="PLT-001", material="Steel S235", thickness=3, width=80, flange_a=120,
    holes=[
        Hole(from_edge=15, from_left=15, diameter=9),
        Hole(from_edge=15, from_left=105, diameter=9),
        Hole(from_edge=65, from_left=15, diameter=9),
        Hole(from_edge=65, from_left=105, diameter=9),
        Hole(from_edge=40, from_left=60, diameter=20),
    ],
)
BRACKET = Part(
    part_type="l_bracket", name="BRK-001", material="Steel S235", thickness=3, width=60,
    flange_a=80, flange_b=50, bend_radius=3,
    holes=[
        Hole(flange="A", from_edge=20, from_left=15, diameter=9),
        Hole(flange="A", from_edge=20, from_left=45, diameter=9),
        Hole(flange="B", from_edge=20, from_left=30, diameter=11),
    ],
)
SKETCH = Part(
    part_type="l_bracket", name="BRK-002", material="Steel S235", thickness=2, width=40,
    flange_a=60, flange_b=40, bend_radius=2,
    holes=[
        Hole(flange="A", from_edge=15, from_left=10, diameter=7),
        Hole(flange="A", from_edge=15, from_left=30, diameter=7),
        Hole(flange="B", from_edge=15, from_left=20, diameter=9),
    ],
)

PLATE_CHANGES = [
    Change(action="modify_hole", hole_number=5, field="diameter", number_value=25, markup_text="Ø25"),
    Change(action="modify_hole", hole_number=1, field="from_edge", number_value=20, markup_text="H1 + H2: 20 from bottom"),
    Change(action="modify_hole", hole_number=2, field="from_edge", number_value=20, markup_text="H1 + H2: 20 from bottom"),
]
BRACKET_CHANGES = [
    Change(action="modify_hole", hole_number=3, field="diameter", number_value=14, markup_text="Ø14"),
    Change(
        action="add_hole",
        new_hole=Hole(flange="A", from_edge=50, from_left=30, diameter=6),
        markup_text="ADD HOLE Ø6, flange A, 50 from free edge, 30 from left",
    ),
]


# --- Drawing helpers ---------------------------------------------------------------


def px(mm_value: float) -> float:
    return mm_value * DPI / 25.4


def page_xy(x_mm: float, y_mm: float) -> tuple[float, float]:
    """Sheet millimetres (origin bottom-left) to image pixels (origin top-left)."""
    return px(x_mm), px(PAGE_H - y_mm)


def wobbly(draw: ImageDraw.ImageDraw, rng: random.Random, p1, p2, fill, width=4, jitter=1.6) -> None:
    """A hand-drawn straight line."""
    (x1, y1), (x2, y2) = p1, p2
    length = math.hypot(x2 - x1, y2 - y1)
    steps = max(2, int(length / 28))
    nx, ny = (-(y2 - y1) / length, (x2 - x1) / length) if length else (0, 0)
    bow = rng.uniform(-1, 1) * min(6.0, length / 60)
    points = []
    for i in range(steps + 1):
        f = i / steps
        offset = bow * math.sin(math.pi * f) + rng.uniform(-jitter, jitter)
        points.append((x1 + (x2 - x1) * f + nx * offset, y1 + (y2 - y1) * f + ny * offset))
    draw.line(points, fill=fill, width=width, joint="curve")


def wobbly_circle(draw, rng, centre, radius, fill, width=4) -> None:
    cx, cy = centre
    start = rng.uniform(0, math.tau)
    points = []
    for i in range(41):  # slightly more than a full turn, like a pen
        angle = start + math.tau * 1.04 * i / 40
        r = radius * (1 + 0.05 * math.sin(angle * 2 + start) + rng.uniform(-0.02, 0.02))
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.line(points, fill=fill, width=width, joint="curve")


def hand_text(image: Image.Image, rng, xy, text, size, fill, angle=None) -> None:
    font = hand_font(size)
    box = font.getbbox(text)
    layer = Image.new("RGBA", (box[2] + 20, box[3] + 20), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((10, 10), text, font=font, fill=fill + (255,))
    layer = layer.rotate(rng.uniform(-3, 3) if angle is None else angle, expand=True, resample=Image.BICUBIC)
    image.paste(layer, (int(xy[0]), int(xy[1])), layer)


def arrow(draw, rng, tail, tip, fill, width=4) -> None:
    wobbly(draw, rng, tail, tip, fill, width)
    angle = math.atan2(tip[1] - tail[1], tip[0] - tail[0])
    for spread in (0.45, -0.45):
        end = (tip[0] - 26 * math.cos(angle + spread), tip[1] - 26 * math.sin(angle + spread))
        draw.line([tip, end], fill=fill, width=width)


def as_phone_photo(sheet: Image.Image, rng: random.Random) -> Image.Image:
    """Lay the sheet on a desk and 'photograph' it: slight perspective, uneven
    light, a little blur and sensor noise."""
    w, h = sheet.size
    margin = 110
    canvas_size = (w + 2 * margin, h + 2 * margin)
    desk = Image.new("RGB", canvas_size, (94, 78, 62))
    grain = Image.effect_noise(canvas_size, 22).convert("L")
    desk = Image.blend(desk, Image.merge("RGB", (grain, grain, grain)), 0.10)

    # Paper is never pure white in a photo.
    paper = Image.blend(sheet, Image.new("RGB", sheet.size, (236, 232, 222)), 0.22)
    mask = Image.new("L", sheet.size, 255)

    # Corners of the sheet on the canvas: top-left, bottom-left, bottom-right, top-right.
    corners = [
        (margin + rng.uniform(8, 30), margin + rng.uniform(10, 34)),
        (margin - rng.uniform(10, 40), margin + h - rng.uniform(0, 16)),
        (margin + w + rng.uniform(6, 36), margin + h + rng.uniform(0, 20)),
        (margin + w - rng.uniform(14, 44), margin + rng.uniform(-6, 18)),
    ]
    coeffs = _perspective_coeffs(corners, [(0, 0), (0, h), (w, h), (w, 0)])
    warped = paper.transform(canvas_size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    warped_mask = mask.transform(canvas_size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)

    shadow = warped_mask.filter(ImageFilter.GaussianBlur(14))
    desk.paste(Image.new("RGB", canvas_size, (40, 32, 26)), (10, 14), shadow.point(lambda v: int(v * 0.5)))
    desk.paste(warped, (0, 0), warped_mask)

    # Uneven lighting: brighter towards one corner.
    big = (canvas_size[0] * 2, canvas_size[0] * 2)
    light = Image.linear_gradient("L").resize(big).rotate(rng.uniform(20, 60), resample=Image.BICUBIC)
    light = light.crop((big[0] // 4, big[1] // 4, big[0] // 4 + canvas_size[0], big[1] // 4 + canvas_size[1]))
    light = light.point(lambda v: 200 + v * 55 // 255)
    lit = Image.composite(desk, Image.new("RGB", canvas_size, (0, 0, 0)), light)

    lit = lit.filter(ImageFilter.GaussianBlur(0.7))
    noise = Image.effect_noise(canvas_size, 9).convert("L")
    lit = Image.blend(lit, Image.merge("RGB", (noise, noise, noise)), 0.045)
    return lit


def _perspective_coeffs(target: list[tuple], source: list[tuple]) -> list[float]:
    """Coefficients for Image.transform mapping output (target) to input (source)."""
    rows, rhs = [], []
    for (tx, ty), (sx, sy) in zip(target, source):
        rows.append([tx, ty, 1, 0, 0, 0, -sx * tx, -sx * ty])
        rows.append([0, 0, 0, tx, ty, 1, -sy * tx, -sy * ty])
        rhs += [sx, sy]
    return _solve(rows, rhs)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                factor = m[r][col] / m[col][col]
                m[r] = [v - factor * p for v, p in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


# --- The files ---------------------------------------------------------------------


def make_drawing(part: Part, rules: Rules) -> tuple[Path, dict, Image.Image]:
    path = OUT / "drawings" / f"{part.name}.pdf"
    anchors = render_sheet(part, unfold(part, rules), path, show_flat=False, date=DATE)
    pix = pymupdf.open(path)[0].get_pixmap(dpi=DPI)
    return path, anchors, Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def strike_cell(image, draw, rng, anchors, tag: str, column: int, new_text: str) -> None:
    """Cross out one hole-table cell and write the new value next to the table."""
    x, y, widths = anchors[f"row:{tag}"][0]
    left = x + sum(widths[:column])
    a = page_xy(left + widths[column] * 0.22, y - 0.4)
    b = page_xy(left + widths[column] * 0.78, y + 0.6)
    wobbly(draw, rng, a, b, RED, width=4, jitter=0.8)
    tx, ty = page_xy(x + sum(widths) + 2.5, y + 3.4)
    hand_text(image, rng, (tx, ty - 8), new_text, 40, RED, angle=rng.uniform(-2, 2))


def make_plate_markup(sheet: Image.Image, anchors: dict, rng) -> Image.Image:
    image = sheet.copy()
    draw = ImageDraw.Draw(image)

    # H5: bigger hole.
    x, y, r = anchors["H5"][0]
    centre = page_xy(x, y)
    wobbly_circle(draw, rng, centre, px(r) * 1.28, RED)
    tail = (centre[0] + px(r) + 230, centre[1] - 190)
    arrow(draw, rng, tail, (centre[0] + px(r) * 1.05, centre[1] - px(r) * 0.75), RED)
    hand_text(image, rng, (tail[0] + 4, tail[1] - 78), "Ø25", 74, RED)
    strike_cell(image, draw, rng, anchors, "H5", 3, "Ø25")

    # H1 and H2: move up.
    for tag in ("H1", "H2"):
        hx, hy, hr = anchors[tag][0]
        c = page_xy(hx, hy)
        arrow(draw, rng, (c[0], c[1] - px(hr) - 8), (c[0], c[1] - px(hr) - 78), RED)
        strike_cell(image, draw, rng, anchors, tag, 1, "20")
    h1, h2 = page_xy(*anchors["H1"][0][:2]), page_xy(*anchors["H2"][0][:2])
    mid = ((h1[0] + h2[0]) / 2, h1[1])
    hand_text(image, rng, (mid[0] - 330, mid[1] + 6), "H1 + H2: 20 from bottom", 58, RED, angle=1.5)
    return as_phone_photo(image, rng)


def make_bracket_markup(sheet: Image.Image, anchors: dict, rng) -> Image.Image:
    image = sheet.copy()
    draw = ImageDraw.Draw(image)

    # H3: bigger hole (in the front view).
    x, y, r = anchors["H3"][0]
    centre = page_xy(x, y)
    wobbly_circle(draw, rng, centre, px(r) * 1.5, RED)
    tail = (centre[0] + 330, centre[1] + 40)
    arrow(draw, rng, tail, (centre[0] + px(r) * 1.7, centre[1] + 8), RED)
    hand_text(image, rng, (tail[0] + 10, tail[1] - 50), "Ø14", 74, RED)
    strike_cell(image, draw, rng, anchors, "H3", 4, "Ø14")

    # New hole on flange A (top view): 50 from the free edge, 30 from the left.
    h1x, h1y, h1r = anchors["H1"][0]
    scale = h1r / (BRACKET.holes[0].diameter / 2)
    new_x = h1x + (30 - BRACKET.holes[0].from_left) * scale
    new_y = h1y + (50 - BRACKET.holes[0].from_edge) * scale
    c = page_xy(new_x, new_y)
    wobbly_circle(draw, rng, c, px(3 * scale), RED)
    draw.line([(c[0] - 26, c[1]), (c[0] + 26, c[1])], fill=RED, width=3)
    draw.line([(c[0], c[1] - 26), (c[0], c[1] + 26)], fill=RED, width=3)
    tail = (c[0] + 330, c[1] - 30)
    arrow(draw, rng, tail, (c[0] + 30, c[1] - 4), RED)
    hand_text(image, rng, (tail[0] + 12, tail[1] - 84), "ADD HOLE Ø6", 66, RED)
    hand_text(image, rng, (tail[0] + 12, tail[1] - 6), "flange A", 50, RED)
    hand_text(image, rng, (tail[0] + 12, tail[1] + 52), "50 from free edge", 50, RED)
    hand_text(image, rng, (tail[0] + 12, tail[1] + 110), "30 from left", 50, RED)
    return as_phone_photo(image, rng)


def make_sketch(rng) -> Image.Image:
    """A freehand sketch of BRK-002 on squared paper."""
    w, h = 2200, 1560
    image = Image.new("RGB", (w, h), (247, 245, 238))
    draw = ImageDraw.Draw(image)
    for gx in range(0, w, 44):
        draw.line([(gx, 0), (gx, h)], fill=(214, 224, 234), width=1)
    for gy in range(0, h, 44):
        draw.line([(0, gy), (w, gy)], fill=(214, 224, 234), width=1)

    def line(p1, p2, width=5):
        wobbly(draw, rng, p1, p2, INK, width=width, jitter=2.2)

    def dim(p1, p2, text, text_xy, size=58):
        wobbly(draw, rng, p1, p2, INK, width=3, jitter=1.4)
        for p in (p1, p2):  # tick marks
            draw.line([(p[0] - 12, p[1] + 12), (p[0] + 12, p[1] - 12)], fill=INK, width=3)
        hand_text(image, rng, text_xy, text, size, INK)

    hand_text(image, rng, (90, 50), "Bracket  BRK-002", 84, INK, angle=-1)
    hand_text(image, rng, (100, 170), "2 mm  S235", 62, INK, angle=0.5)
    hand_text(image, rng, (100, 250), "inside bend R2", 56, INK, angle=-0.5)

    # Side profile, bottom-left. 9 px per mm.
    s = 9
    ox, oy = 150, 1280  # outside corner of the free edge of flange A
    a, b, t = 60 * s, 40 * s, 2 * s
    line((ox, oy), (ox + a - 26, oy))
    draw.arc([ox + a - 62, oy - 62, ox + a, oy], 0, 90, fill=INK, width=5)
    line((ox + a, oy - 28), (ox + a, oy - b))
    line((ox + a, oy - b), (ox + a - t, oy - b))
    line((ox + a - t, oy - b), (ox + a - t, oy - t - 22))
    line((ox + a - t - 20, oy - t), (ox, oy - t))
    line((ox, oy - t), (ox, oy))
    dim((ox, oy + 70), (ox + a, oy + 70), "60", (ox + a / 2 - 30, oy + 78))
    dim((ox + a + 70, oy), (ox + a + 70, oy - b), "40", (ox + a + 88, oy - b / 2 - 40))
    hand_text(image, rng, (ox + 60, oy - 150), "flange A", 50, INK)
    hand_text(image, rng, (ox + a - 215, oy - b - 78), "flange B", 50, INK)
    hand_text(image, rng, (ox + 30, oy + 150), "(outside dims)", 46, INK)

    # Flange A face, top-right: 40 wide x 60 long, free edge at the bottom.
    fx, fy = 1000, 760  # bottom-left corner
    fw, fl = 40 * s, 60 * s
    line((fx, fy), (fx + fw, fy))
    line((fx + fw, fy), (fx + fw, fy - fl))
    line((fx + fw, fy - fl), (fx, fy - fl))
    line((fx, fy - fl), (fx, fy))
    hand_text(image, rng, (fx + 40, fy - fl - 76), "flange A", 54, INK)
    hand_text(image, rng, (fx + fw + 24, fy - fl - 8), "bend", 44, INK)
    for from_left in (10, 30):
        wobbly_circle(draw, rng, (fx + from_left * s, fy - 15 * s), 3.5 * s, INK, width=5)
    hand_text(image, rng, (fx + 96, fy - 15 * s - 124), "2x Ø7", 56, INK)
    dim((fx, fy + 60), (fx + fw, fy + 60), "40", (fx + fw / 2 - 30, fy + 66))
    dim((fx, fy + 150), (fx + 10 * s, fy + 150), "10", (fx + 10 * s + 20, fy + 118), size=50)
    dim((fx, fy + 230), (fx + 30 * s, fy + 230), "30", (fx + 30 * s + 20, fy + 198), size=50)
    dim((fx - 70, fy), (fx - 70, fy - 15 * s), "15", (fx - 160, fy - 15 * s / 2 - 36), size=50)
    hand_text(image, rng, (fx - 250, fy + 30), "free edge", 44, INK)

    # Flange B face, right: 40 wide x 40 high, free edge at the top.
    bx, by = 1640, 700  # bottom-left corner (the bend)
    bw, bh = 40 * s, 40 * s
    line((bx, by), (bx + bw, by))
    line((bx + bw, by), (bx + bw, by - bh))
    line((bx + bw, by - bh), (bx, by - bh))
    line((bx, by - bh), (bx, by))
    hand_text(image, rng, (bx + 60, by - bh - 150), "flange B", 54, INK)
    hand_text(image, rng, (bx + 70, by - bh - 84), "free edge", 44, INK)
    hand_text(image, rng, (bx + 130, by + 14), "bend", 44, INK)
    wobbly_circle(draw, rng, (bx + 20 * s, by - bh + 15 * s), 4.5 * s, INK, width=5)
    hand_text(image, rng, (bx + 20 * s + 50, by - bh + 15 * s - 30), "Ø9", 56, INK)
    dim((bx + bw + 60, by - bh), (bx + bw + 60, by - bh + 15 * s), "15", (bx + bw + 76, by - bh + 28), size=50)
    dim((bx, by + 110), (bx + 20 * s, by + 110), "20", (bx + 20 * s + 22, by + 78), size=50)
    dim((bx, by + 200), (bx + bw, by + 200), "40", (bx + bw / 2 - 30, by + 206), size=50)

    hand_text(image, rng, (1000, 1330), "holes measured from free edge + from left", 46, INK, angle=-0.6)
    return as_phone_photo(image, rng)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    rules = Rules.load()
    rng = random.Random(20261008)
    for sub in ("drawings", "markups", "sketches"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    key: dict[str, dict] = {}
    for part, changes, make_markup in [(PLATE, PLATE_CHANGES, make_plate_markup), (BRACKET, BRACKET_CHANGES, make_bracket_markup)]:
        assert not check(resolve(part, rules), rules), part.name
        pdf, anchors, sheet = make_drawing(part, rules)
        key[f"drawings/{pdf.name}"] = {
            "kind": "drawing",
            "sha256": sha256(pdf),
            "part": part.model_dump(),
            "uncertain_fields": [],
            "expected_flat_length": round(unfold(part, rules).flat_length, 2),
        }
        photo = OUT / "markups" / f"{part.name}_markup.jpg"
        make_markup(sheet, anchors, rng).save(photo, quality=86)
        changed, applied, problems = apply_changes(part, changes)
        assert not problems and not check(resolve(changed, rules), rules), part.name
        key[f"markups/{photo.name}"] = {
            "kind": "markup",
            "sha256": sha256(photo),
            "base": part.name,
            "changes": [c.model_dump() for c in changes],
            "expected_changes": [a.label for a in applied],
            "expected_part": changed.model_dump(),
            "expected_flat_length": round(unfold(resolve(changed, rules), rules).flat_length, 2),
        }

    assert not check(resolve(SKETCH, rules), rules)
    sketch = OUT / "sketches" / f"{SKETCH.name}_sketch.jpg"
    make_sketch(rng).save(sketch, quality=86)
    key[f"sketches/{sketch.name}"] = {
        "kind": "sketch",
        "sha256": sha256(sketch),
        "part": SKETCH.model_dump(),
        # Shown as "check this" in offline demo mode, to demonstrate the highlight.
        "uncertain_fields": ["flange_b"],
        "expected_flat_length": round(unfold(SKETCH, rules).flat_length, 2),
    }

    (OUT / "answer_key.json").write_text(json.dumps({
        "note": "PLACEHOLDER test material generated by tools/make_test_data.py. Replace with the domain expert's files and answer key.",
        "rules_version": rules.version,
        "files": key,
    }, indent=2, ensure_ascii=False))
    for name, entry in key.items():
        print(f"{name:38s} {entry['kind']:8s} flat length {entry['expected_flat_length']}")


if __name__ == "__main__":
    main()
