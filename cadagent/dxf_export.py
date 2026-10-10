"""Flat pattern outputs: a DXF for laser cutting and an SVG preview for the web page."""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import units

from .flat import FlatPattern
from .models import Part, fmt

# Layer name -> (AutoCAD colour index, linetype)
LAYERS = {
    "OUTLINE": (7, "CONTINUOUS"),
    "HOLES": (1, "CONTINUOUS"),
    "BEND": (3, "DASHED"),
    "DIMENSIONS": (5, "CONTINUOUS"),
    "TEXT": (5, "CONTINUOUS"),
}


def export_dxf(part: Part, flat: FlatPattern, path: Path) -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.units = units.MM
    doc.header["$MEASUREMENT"] = 1
    for name, (colour, linetype) in LAYERS.items():
        doc.layers.add(name, color=colour, linetype=linetype)
    msp = doc.modelspace()

    w, h = flat.size_x, flat.size_y
    msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True, dxfattribs={"layer": "OUTLINE"})
    for hole in flat.holes:
        msp.add_circle((hole.x, hole.y), hole.diameter / 2, dxfattribs={"layer": "HOLES"})
    if flat.bend_line_y is not None:
        msp.add_line((0, flat.bend_line_y), (w, flat.bend_line_y), dxfattribs={"layer": "BEND"})

    text_height = max(2.5, min(w, h) / 25)
    dim_style = {
        "dimtxt": text_height,
        "dimasz": text_height,
        "dimexo": text_height * 0.4,
        "dimexe": text_height * 0.5,
        "dimgap": text_height * 0.3,
        "dimdec": 2,
        "dimzin": 8,
    }
    offset = text_height * 4

    def linear(p1, p2, base, angle=0.0):
        dim = msp.add_linear_dim(
            base=base, p1=p1, p2=p2, angle=angle, dimstyle="EZDXF", override=dim_style,
            dxfattribs={"layer": "DIMENSIONS"},
        )
        dim.render()

    linear((0, 0), (w, 0), base=(0, -offset))
    linear((w, 0), (w, h), base=(w + offset, 0), angle=90)
    if flat.bend_line_y is not None:
        linear((0, 0), (0, flat.bend_line_y), base=(-offset, 0), angle=90)

    note = f"{part.name or 'PART'}  |  {part.material}  |  t = {fmt(part.thickness)} mm"
    if flat.bend_line_y is not None:
        note += (
            f"  |  FLAT LENGTH {fmt(flat.flat_length)} mm"
            f"  |  BEND 90 DEG UP, R{fmt(part.bend_radius)}, K = {fmt(flat.k_factor)}"
        )
    msp.add_text(
        note, height=text_height, dxfattribs={"layer": "TEXT"}
    ).set_placement((0, -offset * 2.2))

    doc.saveas(path)


def flat_svg(part: Part, flat: FlatPattern) -> str:
    """A small, theme-aware SVG of the flat pattern (uses currentColor)."""
    w, h = flat.size_x, flat.size_y
    pad = max(w, h) * 0.22 + 12
    font = max(w, h) / 26 + 2
    stroke = max(w, h) / 320 + 0.25
    # SVG y runs down, the flat pattern's y runs up.
    def y(v: float) -> float:
        return h - v

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-pad:.2f} {-pad:.2f} {w + 2 * pad:.2f} {h + 2 * pad:.2f}" '
        f'font-family="ui-sans-serif, system-ui, sans-serif" font-size="{font:.2f}" fill="none" '
        f'stroke="currentColor" stroke-width="{stroke:.2f}" stroke-linejoin="round">',
        f'<rect class="fp-outline" x="0" y="0" width="{w:.3f}" height="{h:.3f}" stroke-width="{stroke * 1.8:.2f}"/>',
    ]
    if flat.bend_line_y is not None:
        by = y(flat.bend_line_y)
        dash = max(w, h) / 40
        out.append(
            f'<line class="fp-bend" x1="0" y1="{by:.3f}" x2="{w:.3f}" y2="{by:.3f}" '
            f'stroke-dasharray="{dash:.2f} {dash / 2:.2f}"/>'
        )
        out.append(
            f'<text class="fp-bend-label" x="{w / 2:.2f}" y="{by - font * 0.4:.2f}" text-anchor="middle" '
            f'stroke="none" fill="currentColor" font-size="{font * 0.8:.2f}">bend line · 90° up</text>'
        )
    for hole in flat.holes:
        cx, cy, r = hole.x, y(hole.y), hole.diameter / 2
        tick = r + font * 0.3
        out.append(f'<circle class="fp-hole" cx="{cx:.3f}" cy="{cy:.3f}" r="{r:.3f}" stroke-width="{stroke * 1.8:.2f}"/>')
        out.append(
            f'<path class="fp-centre" d="M{cx - tick:.2f} {cy:.2f}H{cx + tick:.2f}M{cx:.2f} {cy - tick:.2f}V{cy + tick:.2f}" '
            f'stroke-width="{stroke * 0.6:.2f}" opacity="0.6"/>'
        )
        # Tag to the right of the hole, or to the left when the hole is in the right half.
        on_left = hole.x > w / 2
        tx = cx - r - font * 0.35 if on_left else cx + r + font * 0.35
        out.append(
            f'<text class="fp-tag" x="{tx:.2f}" y="{cy - r - font * 0.15:.2f}" stroke="none" '
            f'text-anchor="{"end" if on_left else "start"}" '
            f'fill="currentColor" font-size="{font * 0.85:.2f}">H{hole.number} Ø{fmt(hole.diameter)}</text>'
        )

    gap = pad * 0.45
    arrow = font * 0.5

    def dim_h(x1, x2, yy, label):
        out.append(
            f'<path class="fp-dim" d="M{x1:.2f} {yy:.2f}H{x2:.2f}M{x1:.2f} {yy - arrow:.2f}V{yy + arrow:.2f}'
            f'M{x2:.2f} {yy - arrow:.2f}V{yy + arrow:.2f}" opacity="0.75"/>'
        )
        out.append(
            f'<text class="fp-dim-text" x="{(x1 + x2) / 2:.2f}" y="{yy + font * 1.15:.2f}" text-anchor="middle" '
            f'stroke="none" fill="currentColor">{label}</text>'
        )

    def dim_v(y1, y2, xx, label, side=1):
        out.append(
            f'<path class="fp-dim" d="M{xx:.2f} {y1:.2f}V{y2:.2f}M{xx - arrow:.2f} {y1:.2f}H{xx + arrow:.2f}'
            f'M{xx - arrow:.2f} {y2:.2f}H{xx + arrow:.2f}" opacity="0.75"/>'
        )
        tx = xx + side * font * 0.9
        ty = (y1 + y2) / 2
        out.append(
            f'<text class="fp-dim-text" x="{tx:.2f}" y="{ty:.2f}" text-anchor="middle" dominant-baseline="middle" '
            f'transform="rotate(-90 {tx:.2f} {ty:.2f})" stroke="none" fill="currentColor">{label}</text>'
        )

    dim_h(0, w, h + gap, fmt(w))
    dim_v(0, h, w + gap, fmt(h))
    if flat.bend_line_y is not None:
        dim_v(y(flat.bend_line_y), h, -gap, fmt(flat.bend_line_y), side=-1)
    out.append("</svg>")
    return "".join(out)
