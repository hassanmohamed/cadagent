"""Markup changes: apply the changes read from a marked-up print to the current
part and describe each one as "was -> now"."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .models import Hole, Part, fmt

HoleField = Literal["diameter", "from_edge", "from_left", "flange"]
PartField = Literal["name", "material", "thickness", "width", "flange_a", "flange_b", "bend_radius"]


class Change(BaseModel):
    """One change as read from the markup. Hole numbers are 1-based and refer to
    the part before any change is applied."""

    action: Literal["modify_hole", "add_hole", "remove_hole", "set_field"]
    hole_number: int | None = None
    field: HoleField | PartField | None = None
    number_value: float | None = None
    text_value: str | None = None
    new_hole: Hole | None = None
    uncertain: bool = False
    markup_text: str = ""


class AppliedChange(BaseModel):
    label: str
    paths: list[str] = []
    uncertain: bool = False
    markup_text: str = ""


def field_label(part: Part, field: str) -> str:
    bracket = part.is_bracket
    return {
        "name": "Name",
        "material": "Material",
        "thickness": "Thickness",
        "width": "Width",
        "flange_a": "Flange A" if bracket else "Length",
        "flange_b": "Flange B",
        "bend_radius": "Inner bend radius",
        "from_edge": "from free edge" if bracket else "from bottom",
        "from_left": "from left",
    }.get(field, field)


def _show(value) -> str:
    if value is None:
        return "—"
    return fmt(value) if isinstance(value, (int, float)) else str(value)


def apply_changes(part: Part, changes: list[Change]) -> tuple[Part, list[AppliedChange], list[str]]:
    """Returns the changed part, the was -> now list and any changes that could
    not be applied (in plain words)."""
    new = part.model_copy(deep=True)
    applied: list[AppliedChange] = []
    problems: list[str] = []
    removals: list[tuple[int, Change]] = []
    count = len(part.holes)

    def hole_index(change: Change) -> int | None:
        n = change.hole_number
        if n is None or not 1 <= n <= count:
            problems.append(
                f'A markup refers to Hole {n if n is not None else "?"}, but the current part has {count} '
                f'hole{"" if count == 1 else "s"}. Is this markup for a different part?'
            )
            return None
        return n - 1

    for change in changes:
        if change.action == "modify_hole":
            i = hole_index(change)
            if i is None:
                continue
            hole = new.holes[i]
            if change.field == "flange":
                value = (change.text_value or "").strip().upper()
                if value not in ("A", "B") or not part.is_bracket:
                    problems.append(f"Hole {i + 1}: could not move it to flange '{change.text_value}'.")
                    continue
                was, hole.flange = hole.flange, value
                label = f"Hole {i + 1}: Flange {was} → Flange {value}"
            elif change.field in ("diameter", "from_edge", "from_left") and change.number_value is not None:
                was = getattr(hole, change.field)
                setattr(hole, change.field, change.number_value)
                if change.field == "diameter":
                    label = f"Hole {i + 1}: Ø{fmt(was)} → Ø{fmt(change.number_value)}"
                else:
                    label = f"Hole {i + 1}: {field_label(part, change.field)} {fmt(was)} → {fmt(change.number_value)}"
            else:
                problems.append(f"Hole {i + 1}: a markup could not be understood ({change.markup_text or 'no text'}).")
                continue
            applied.append(AppliedChange(label=label, paths=[f"holes.{i}.{change.field}"], uncertain=change.uncertain, markup_text=change.markup_text))

        elif change.action == "remove_hole":
            i = hole_index(change)
            if i is not None:
                removals.append((i, change))

        elif change.action == "add_hole":
            if change.new_hole is None:
                problems.append(f"A hole was added by markup but its size or position could not be read ({change.markup_text or 'no text'}).")
                continue
            hole = change.new_hole.model_copy()
            if not part.is_bracket:
                hole.flange = "A"
            new.holes.append(hole)
            i = len(new.holes) - 1
            where = f"Flange {hole.flange}, " if part.is_bracket else ""
            label = (
                f"Hole {i + 1}: added — Ø{fmt(hole.diameter)}, {where}"
                f"{fmt(hole.from_edge)} {field_label(part, 'from_edge')}, {fmt(hole.from_left)} from left"
            )
            applied.append(AppliedChange(
                label=label,
                paths=[f"holes.{i}.{f}" for f in ("flange", "from_edge", "from_left", "diameter")],
                uncertain=change.uncertain,
                markup_text=change.markup_text,
            ))

        elif change.action == "set_field":
            field = change.field
            if field in ("name", "material"):
                if not change.text_value:
                    problems.append(f"{field_label(part, field)}: the new value could not be read.")
                    continue
                was = getattr(new, field)
                setattr(new, field, change.text_value)
                label = f"{field_label(part, field)}: {_show(was)} → {change.text_value}"
            elif field in ("thickness", "width", "flange_a", "flange_b", "bend_radius") and change.number_value is not None:
                was = getattr(new, field)
                setattr(new, field, change.number_value)
                label = f"{field_label(part, field)}: {_show(was)} → {fmt(change.number_value)}"
            else:
                problems.append(f"A markup could not be understood ({change.markup_text or 'no text'}).")
                continue
            applied.append(AppliedChange(label=label, paths=[field], uncertain=change.uncertain, markup_text=change.markup_text))

    # Remove last, highest number first, so hole numbers keep referring to the original part.
    # Paths of later holes are shifted to match the renumbered form.
    for i, change in sorted(removals, key=lambda item: -item[0]):
        hole = new.holes.pop(i)
        for other in applied:
            other.paths = [_shift_path(p, i) for p in other.paths]
        applied.append(AppliedChange(
            label=f"Hole {i + 1}: removed (was Ø{fmt(hole.diameter)})",
            uncertain=change.uncertain,
            markup_text=change.markup_text,
        ))
    if removals:
        applied.append(AppliedChange(label="Remaining holes were renumbered after the removal."))

    return new, applied, problems


def _shift_path(path: str, removed_index: int) -> str:
    parts = path.split(".")
    if len(parts) == 3 and parts[0] == "holes" and int(parts[1]) > removed_index:
        parts[1] = str(int(parts[1]) - 1)
    return ".".join(parts)
