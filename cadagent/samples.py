"""The bundled test files, offered as one-click samples in both front ends."""

from __future__ import annotations

from pathlib import Path

TEST_DATA = Path(__file__).resolve().parent.parent / "test_data"

SAMPLES = [
    {"file": "drawings/PLT-001.pdf", "label": "Plate drawing", "detail": "PLT-001 · PDF", "mode": "create", "request": "Create this part"},
    {"file": "drawings/BRK-001.pdf", "label": "L-bracket drawing", "detail": "BRK-001 · PDF", "mode": "create", "request": "Create this part"},
    {"file": "markups/PLT-001_markup.jpg", "label": "Plate markup", "detail": "PLT-001 · photo", "mode": "markup", "request": "Apply the markups"},
    {"file": "markups/BRK-001_markup.jpg", "label": "L-bracket markup", "detail": "BRK-001 · photo", "mode": "markup", "request": "Apply the markups"},
    {"file": "sketches/BRK-002_sketch.jpg", "label": "Hand sketch", "detail": "BRK-002 · photo", "mode": "create", "request": "Create this part from my sketch"},
]


def available_samples() -> list[dict]:
    return [s for s in SAMPLES if (TEST_DATA / s["file"]).exists()]
