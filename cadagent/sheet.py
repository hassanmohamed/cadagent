"""Drawing sheet (PDF): front and side views, flat pattern, key dimensions,
hole table, title block and a one-row parts list. A simple A3 sheet for review,
not Inventor quality.

The same renderer produces the bundled test drawings (with `show_flat=False`).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from .flat import FlatPattern
from .models import Part, fmt

PAGE_W, PAGE_H = 420.0, 297.0  # A3 landscape, mm
FRAME = 10.0
VIEWS_BOTTOM, VIEWS_TOP = 66.0, PAGE_H - FRAME - 5
SCALES = [(10, "10:1"), (5, "5:1"), (2, "2:1"), (1, "1:1"), (0.5, "1:2"), (0.2, "1:5"), (0.1, "1:10"), (0.05, "1:20")]

VISIBLE, THIN = 0.5, 0.18
FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"
DIM_TEXT = 3.2  # mm


class Pen:
    """Thin wrapper over the canvas working in page millimetres."""

    def __init__(self, canvas: Canvas):
        self.c = canvas
        # Where things ended up on the page (mm), e.g. "H1" -> [(x, y, r), ...] and
        # "row:H1" -> [(x, y_centre, column widths)]. Used to place test markups.
        self.anchors: dict[str, list[tuple]] = {}

    def style(self, width: float = VISIBLE, dash: tuple | None = None) -> None:
        self.c.setLineWidth(width * mm)
        self.c.setDash([d * mm for d in dash] if dash else [])
        self.c.setStrokeColorRGB(0, 0, 0)
        self.c.setFillColorRGB(0, 0, 0)

    def line(self, x1, y1, x2, y2) -> None:
        self.c.line(x1 * mm, y1 * mm, x2 * mm, y2 * mm)

    def rect(self, x, y, w, h) -> None:
        self.c.rect(x * mm, y * mm, w * mm, h * mm, stroke=1, fill=0)

    def circle(self, x, y, r) -> None:
        self.c.circle(x * mm, y * mm, r * mm, stroke=1, fill=0)

    def arc(self, cx, cy, r, start_deg, extent_deg) -> None:
        self.c.arc((cx - r) * mm, (cy - r) * mm, (cx + r) * mm, (cy + r) * mm, start_deg, extent_deg)

    def text(self, x, y, s, size=DIM_TEXT, bold=False, align="left", angle=0.0) -> None:
        self.c.saveState()
        self.c.setFont(FONT_BOLD if bold else FONT, size * mm / 0.7)  # size = approximate cap height
        self.c.translate(x * mm, y * mm)
        if angle:
            self.c.rotate(angle)
        draw = {"left": self.c.drawString, "centre": self.c.drawCentredString, "right": self.c.drawRightString}[align]
        draw(0, 0, s)
        self.c.restoreState()

    def arrow(self, x, y, dx, dy, size=2.4) -> None:
        """Filled arrowhead with its tip at (x, y), pointing along (dx, dy)."""
        nx, ny = -dy, dx
        path = self.c.beginPath()
        path.moveTo(x * mm, y * mm)
        path.lineTo((x - dx * size + nx * size * 0.18) * mm, (y - dy * size + ny * size * 0.18) * mm)
        path.lineTo((x - dx * size - nx * size * 0.18) * mm, (y - dy * size - ny * size * 0.18) * mm)
        path.close()
        self.c.drawPath(path, stroke=0, fill=1)

    def dim_h(self, x1, x2, y_obj, y_dim, label) -> None:
        """Horizontal dimension between x1 and x2; extension lines start at y_obj."""
        self.style(THIN)
        sign = 1 if y_dim >= y_obj else -1
        for x in (x1, x2):
            self.line(x, y_obj + sign * 1.2, x, y_dim + sign * 1.5)
        self.line(x1, y_dim, x2, y_dim)
        if abs(x2 - x1) > 7:
            self.arrow(x1, y_dim, -1, 0)
            self.arrow(x2, y_dim, 1, 0)
            self.text((x1 + x2) / 2, y_dim + 1.0, label, align="centre")
        else:  # too tight: arrows and text outside
            self.line(x1 - 5, y_dim, x1, y_dim)
            self.line(x2, y_dim, x2 + 5, y_dim)
            self.arrow(x1, y_dim, 1, 0)
            self.arrow(x2, y_dim, -1, 0)
            self.text(x2 + 6, y_dim - DIM_TEXT / 2, label)

    def dim_v(self, y1, y2, x_obj, x_dim, label) -> None:
        """Vertical dimension between y1 and y2; extension lines start at x_obj."""
        self.style(THIN)
        sign = 1 if x_dim >= x_obj else -1
        for y in (y1, y2):
            self.line(x_obj + sign * 1.2, y, x_dim + sign * 1.5, y)
        self.line(x_dim, y1, x_dim, y2)
        if abs(y2 - y1) > 7:
            self.arrow(x_dim, y1, 0, -1)
            self.arrow(x_dim, y2, 0, 1)
            self.text(x_dim - 1.0, (y1 + y2) / 2, label, align="centre", angle=90)
        else:
            self.line(x_dim, y1 - 5, x_dim, y1)
            self.line(x_dim, y2, x_dim, y2 + 5)
            self.arrow(x_dim, y1, 0, 1)
            self.arrow(x_dim, y2, 0, -1)
            self.text(x_dim - 1.0, y2 + 6, label, angle=90)

    def hole(self, x, y, r, tag) -> None:
        self.anchors.setdefault(tag, []).append((x, y, r))
        self.style(VISIBLE)
        self.circle(x, y, r)
        self.style(THIN, dash=(3, 0.8, 0.6, 0.8))
        ext = r + 1.8
        self.line(x - ext, y, x + ext, y)
        self.line(x, y - ext, x, y + ext)
        self.style(THIN)
        self.text(x + r * 0.72 + 1.0, y + r * 0.72 + 0.8, tag, size=2.8, bold=True)

    def label(self, x, y, s) -> None:
        self.text(x, y, s, size=3.0, bold=True, align="centre")


def _pick_scale(fits) -> tuple[float, str]:
    for scale, label in SCALES:
        if fits(scale):
            return scale, label
    return SCALES[-1]


def render_sheet(
    part: Part,
    flat: FlatPattern,
    path: Path,
    *,
    show_flat: bool = True,
    date: str | None = None,
    revision: str = "A",
) -> dict[str, list[tuple]]:
    canvas = Canvas(str(path), pagesize=(PAGE_W * mm, PAGE_H * mm))
    canvas.setTitle(f"{part.name or 'Part'} drawing")
    canvas.setAuthor("AI CAD Agent POC")
    pen = Pen(canvas)

    pen.style(0.7)
    pen.rect(FRAME, FRAME, PAGE_W - 2 * FRAME, PAGE_H - 2 * FRAME)

    if part.is_bracket:
        scale_label = _draw_bracket(pen, part, flat, show_flat)
    else:
        scale_label = _draw_plate(pen, part, flat, show_flat)

    _hole_table(pen, part)
    _notes(pen, part, flat, show_flat)
    _parts_list(pen, part, flat, show_flat)
    _title_block(pen, part, scale_label, date or dt.date.today().isoformat(), revision)

    canvas.showPage()
    canvas.save()
    return pen.anchors


# --- Views -------------------------------------------------------------------


def _draw_plate(pen: Pen, part: Part, flat: FlatPattern, show_flat: bool) -> str:
    length, width, t = part.flange_a, part.width, part.thickness
    left, right = FRAME + 5, PAGE_W - FRAME - 5
    split = right - 95  # front view | side view
    height = VIEWS_TOP - VIEWS_BOTTOM

    def fits(s):
        return length * s + 50 <= split - left and width * s + 46 <= height and t * s + 40 <= right - split

    s, scale_label = _pick_scale(fits)

    # Front view (plan): length horizontal, width vertical.
    x0 = left + (split - left - length * s) / 2 + 6
    y0 = VIEWS_BOTTOM + (height - width * s) / 2
    pen.style(VISIBLE)
    pen.rect(x0, y0, length * s, width * s)
    for i, hole in enumerate(part.holes):
        pen.hole(x0 + hole.from_left * s, y0 + hole.from_edge * s, hole.diameter / 2 * s, f"H{i + 1}")
    pen.dim_h(x0, x0 + length * s, y0 + width * s, y0 + width * s + 11, fmt(length))
    pen.dim_v(y0, y0 + width * s, x0, x0 - 11, fmt(width))
    pen.label(x0 + length * s / 2, y0 - 9, "FRONT VIEW / FLAT PATTERN" if show_flat else "FRONT VIEW")

    # Side view: thickness horizontal, width vertical.
    sx = split + (right - split - t * s) / 2
    pen.style(VISIBLE)
    pen.rect(sx, y0, t * s, width * s)
    pen.dim_h(sx, sx + t * s, y0 + width * s, y0 + width * s + 11, fmt(t))
    pen.label(sx + t * s / 2, y0 - 9, "SIDE VIEW")
    return scale_label


def _draw_bracket(pen: Pen, part: Part, flat: FlatPattern, show_flat: bool) -> str:
    a, b, t, r, w = part.flange_a, part.flange_b, part.thickness, part.bend_radius, part.width
    ro = r + t
    left, right = FRAME + 5, PAGE_W - FRAME - 5
    if show_flat:
        col1, col2 = left + 135, left + 270
    else:
        col1, col2 = left + 190, right
    height = VIEWS_TOP - VIEWS_BOTTOM
    gap = 32  # between front view and top view

    def fits(s):
        ok = w * s + 44 <= col1 - left and a * s + 48 <= col2 - col1
        ok = ok and 22 + b * s + gap + a * s + 14 <= height
        if show_flat:
            ok = ok and w * s + 48 <= right - col2 and flat.size_y * s + 46 <= height
        return ok

    s, scale_label = _pick_scale(fits)

    # Front view: looking at the outside face of Flange B. x = width, y = height.
    fx = left + (col1 - left - w * s) / 2 + 6
    fy = VIEWS_TOP - 22 - b * s
    pen.style(VISIBLE)
    pen.rect(fx, fy, w * s, b * s)
    pen.style(THIN)
    pen.line(fx, fy + ro * s, fx + w * s, fy + ro * s)  # bend tangent line
    for i, hole in enumerate(part.holes):
        if hole.flange == "B":
            pen.hole(fx + hole.from_left * s, fy + (b - hole.from_edge) * s, hole.diameter / 2 * s, f"H{i + 1}")
    pen.dim_h(fx, fx + w * s, fy + b * s, fy + b * s + 11, fmt(w))
    pen.dim_v(fy, fy + b * s, fx, fx - 11, fmt(b))
    pen.label(fx + w * s / 2, fy - 8, "FRONT VIEW  (FLANGE B)")

    # Top view, below the front view: looking down on Flange A. Bend at the top.
    ty = fy - gap - a * s
    pen.style(VISIBLE)
    pen.rect(fx, ty, w * s, a * s)
    pen.line(fx, ty + (a - t) * s, fx + w * s, ty + (a - t) * s)  # inside face of Flange B
    pen.style(THIN)
    pen.line(fx, ty + (a - ro) * s, fx + w * s, ty + (a - ro) * s)  # bend tangent line
    for i, hole in enumerate(part.holes):
        if hole.flange == "A":
            pen.hole(fx + hole.from_left * s, ty + hole.from_edge * s, hole.diameter / 2 * s, f"H{i + 1}")
    pen.dim_v(ty, ty + a * s, fx, fx - 11, fmt(a))
    pen.label(fx + w * s / 2, ty - 8, "TOP VIEW  (FLANGE A)")

    # Side view: the L profile. Free edge of Flange A on the left, Flange B standing on the right.
    sx = col1 + (col2 - col1 - a * s) / 2
    sy = fy
    pen.style(VISIBLE)
    px = lambda v: sx + v * s  # noqa: E731
    py = lambda v: sy + v * s  # noqa: E731
    pen.line(px(0), py(0), px(a - ro), py(0))
    pen.arc(px(a - ro), py(ro), ro * s, 270, 90)
    pen.line(px(a), py(ro), px(a), py(b))
    pen.line(px(a), py(b), px(a - t), py(b))
    pen.line(px(a - t), py(b), px(a - t), py(ro))
    pen.arc(px(a - ro), py(ro), r * s, 270, 90)
    pen.line(px(a - ro), py(t), px(0), py(t))
    pen.line(px(0), py(t), px(0), py(0))
    pen.dim_h(px(0), px(a), py(0), py(0) - 11, fmt(a))
    pen.dim_v(py(0), py(b), px(a), px(a) + 11, fmt(b))
    pen.dim_v(py(0), py(t), px(0), px(0) - 9, fmt(t))
    # Bend radius leader, from the inside of the bend up and to the left.
    pen.style(THIN)
    k = 0.7071
    tip_x, tip_y = px(a - ro) + r * s * k, py(ro) - r * s * k
    end_x, end_y = tip_x - 13, tip_y + 13
    pen.line(tip_x, tip_y, end_x, end_y)
    pen.line(end_x, end_y, end_x - 12, end_y)
    pen.arrow(tip_x, tip_y, k, -k)
    pen.text(end_x - 11.5, end_y + 1.0, f"R{fmt(r)}")
    pen.label(px(a / 2), py(0) - 20, "SIDE VIEW")

    if show_flat:
        fw, fl = flat.size_x, flat.size_y
        gx = col2 + (right - col2 - fw * s) / 2 + 4
        gy = VIEWS_BOTTOM + (height - fl * s) / 2 + 4
        pen.style(VISIBLE)
        pen.rect(gx, gy, fw * s, fl * s)
        pen.style(THIN, dash=(4, 1.5))
        by = gy + flat.bend_line_y * s
        pen.line(gx, by, gx + fw * s, by)
        pen.style(THIN)
        pen.text(gx + fw * s / 2, by + 1.0, "BEND LINE  90° UP", size=2.4, align="centre")
        for hole in flat.holes:
            pen.hole(gx + hole.x * s, gy + hole.y * s, hole.diameter / 2 * s, f"H{hole.number}")
        pen.dim_h(gx, gx + fw * s, gy + fl * s, gy + fl * s + 11, fmt(fw))
        pen.dim_v(gy, gy + fl * s, gx + fw * s, gx + fw * s + 11, fmt(fl))
        pen.dim_v(gy, by, gx, gx - 11, fmt(flat.bend_line_y))
        pen.label(gx + fw * s / 2, gy - 9, "FLAT PATTERN")
    return scale_label


# --- Tables --------------------------------------------------------------------


def _grid(pen: Pen, x, y_top, col_widths, rows, row_h=5.0, header=True) -> None:
    """Draw a table downwards from y_top. rows is a list of lists of strings."""
    total = sum(col_widths)
    pen.style(0.35)
    pen.rect(x, y_top - row_h * len(rows), total, row_h * len(rows))
    pen.style(THIN)
    for i in range(1, len(rows)):
        pen.line(x, y_top - row_h * i, x + total, y_top - row_h * i)
    cx = x
    for width in col_widths[:-1]:
        cx += width
        pen.line(cx, y_top, cx, y_top - row_h * len(rows))
    for i, row in enumerate(rows):
        cx = x
        for width, cell in zip(col_widths, row):
            pen.text(cx + width / 2, y_top - row_h * i - row_h + 1.5, cell, size=2.6, bold=header and i == 0, align="centre")
            cx += width


def _hole_table(pen: Pen, part: Part) -> None:
    x, y_top = FRAME, 60.0
    pen.text(x + 1, y_top + 1.5, "HOLE TABLE", size=2.8, bold=True)
    max_rows = 9
    if part.is_bracket:
        widths = [14, 18, 34, 26, 16]
        rows = [["HOLE", "FLANGE", "FROM FREE EDGE", "FROM LEFT", "DIA"]]
        rows += [[f"H{i + 1}", h.flange, fmt(h.from_edge), fmt(h.from_left), f"Ø{fmt(h.diameter)}"] for i, h in enumerate(part.holes)]
    else:
        widths = [16, 36, 32, 24]
        rows = [["HOLE", "FROM BOTTOM", "FROM LEFT", "DIA"]]
        rows += [[f"H{i + 1}", fmt(h.from_edge), fmt(h.from_left), f"Ø{fmt(h.diameter)}"] for i, h in enumerate(part.holes)]
    if len(rows) == 1:
        rows.append(["-"] * len(widths))
    hidden = len(rows) - 1 - max_rows
    if hidden > 0:
        rows = rows[: max_rows + 1]
    _grid(pen, x, y_top, widths, rows)
    for i in range(1, len(rows)):
        pen.anchors[f"row:{rows[i][0]}"] = [(x, y_top - 5.0 * i - 2.5, tuple(widths))]
    if hidden > 0:
        pen.text(x + sum(widths) + 2, FRAME + 2, f"+{hidden} more holes: see part.json", size=2.4)


def _notes(pen: Pen, part: Part, flat: FlatPattern, show_flat: bool) -> None:
    x, y = FRAME + 114, 61.5
    pen.text(x, y, "NOTES", size=2.8, bold=True)
    lines = ["1. ALL DIMENSIONS IN MM."]
    if part.is_bracket:
        lines += [
            "2. FLANGE LENGTHS ARE OUTSIDE DIMENSIONS.",
            f"3. BEND 90°, INNER RADIUS R{fmt(part.bend_radius)}.",
            "4. HOLES ARE MEASURED FROM THE FREE EDGE OF",
            "    THEIR FLANGE AND FROM THE LEFT SIDE.",
        ]
        if show_flat:
            lines += [
                f"5. FLAT LENGTH {fmt(flat.flat_length)} = A + B - 2(R + T) + BEND",
                f"    ALLOWANCE {fmt(flat.bend_allowance)}  (K-FACTOR {fmt(flat.k_factor)}).",
            ]
    else:
        lines += ["2. HOLES ARE MEASURED FROM THE BOTTOM-LEFT", "    CORNER."]
    for i, line in enumerate(lines):
        pen.text(x, y - 5.5 - i * 5.0, line, size=2.5)


def _parts_list(pen: Pen, part: Part, flat: FlatPattern, show_flat: bool) -> None:
    x, y_top = PAGE_W - FRAME - 180, 58.0
    flat_size = f"{fmt(flat.size_x)} x {fmt(flat.size_y)}" if show_flat else "-"
    rows = [
        ["ITEM", "PART NO.", "DESCRIPTION", "MATERIAL", "THK", "FLAT SIZE", "QTY"],
        ["1", part.name or "-", "L-BRACKET" if part.is_bracket else "FLAT PLATE", part.material, fmt(part.thickness), flat_size, "1"],
    ]
    _grid(pen, x, y_top, [12, 32, 30, 40, 12, 40, 14], rows, row_h=6.0)


def _title_block(pen: Pen, part: Part, scale_label: str, date: str, revision: str) -> None:
    x, y, w, h = PAGE_W - FRAME - 180, FRAME, 180.0, 36.0
    pen.style(0.5)
    pen.rect(x, y, w, h)
    pen.style(THIN)
    pen.line(x + 78, y, x + 78, y + h)
    for row in (12, 24):
        pen.line(x + 78, y + row, x + w, y + row)
    for col in (112, 146):
        pen.line(x + col, y, x + col, y + h)

    def cell(cx, cy, caption, value, size=3.2):
        pen.text(cx + 1.5, cy + 8.6, caption, size=1.9)
        pen.text(cx + 1.5, cy + 2.6, value, size=size, bold=True)

    pen.text(x + 2, y + h - 5, "PART NO. / NAME", size=1.9)
    pen.text(x + 3, y + h - 15, part.name or "-", size=6.5, bold=True)
    pen.text(x + 3, y + 11, "L-BRACKET, ONE 90° BEND" if part.is_bracket else "FLAT PLATE", size=2.8)
    pen.text(x + 3, y + 4.5, "SHEET-METAL PART", size=2.4)

    cell(x + 78, y + 24, "MATERIAL", part.material, size=2.9)
    cell(x + 112, y + 24, "THICKNESS", f"{fmt(part.thickness)} mm")
    cell(x + 146, y + 24, "SCALE", scale_label)
    cell(x + 78, y + 12, "DRAWN BY", "AI CAD AGENT", size=2.7)
    cell(x + 112, y + 12, "DATE", date, size=2.9)
    cell(x + 146, y + 12, "REV", revision)
    cell(x + 78, y, "UNITS", "mm")
    cell(x + 112, y, "PROJECTION", "FIRST ANGLE", size=2.6)
    cell(x + 146, y, "SHEET", "1 / 1")
