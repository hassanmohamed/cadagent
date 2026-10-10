"""One engineer's working session: read -> confirm -> apply -> undo.

Both front ends use this class, so they behave the same:
  * the local web page (cadagent/app.py) keeps one Session for the laptop;
  * the Streamlit app (streamlit_app.py) keeps one Session per browser session.
"""

from __future__ import annotations

import io
import shutil
import threading
import uuid
import zipfile
from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import reader
from .builder import build_all
from .markup import apply_changes
from .models import Part
from .rules import Rules, check, resolve

MAX_UPLOAD = 25 * 1024 * 1024

_LABELS = {
    "thickness": "Thickness", "width": "Width", "flange_a": "Flange A / Length", "flange_b": "Flange B",
    "bend_radius": "Inner bend radius", "from_edge": "distance from edge", "from_left": "distance from left",
    "diameter": "diameter", "part_type": "Part type", "flange": "flange",
}


class NoPartYet(Exception):
    """A markup was uploaded before any part exists."""


class Version(BaseModel):
    number: int
    part: Part
    summary: dict
    how: str  # what produced this version, shown in the history


def parse_part(raw: dict) -> tuple[Part | None, list[dict]]:
    """Turn the form's values into a Part, reporting blanks in plain words."""
    try:
        return Part.model_validate(raw), []
    except ValidationError as exc:
        issues = []
        for err in exc.errors():
            loc = [str(p) for p in err["loc"]]
            if loc[0] == "holes" and len(loc) == 3:
                message = f"Hole {int(loc[1]) + 1}: {_LABELS.get(loc[2], loc[2])} is missing or not a number."
            else:
                message = f"{_LABELS.get(loc[0], loc[0])} is missing or not a number."
            issues.append({"severity": "error", "field": ".".join(loc), "message": message})
        return None, issues


def check_raw(raw: dict, rules: Rules) -> list[dict]:
    """Check the form's values against the rules without building anything."""
    part, issues = parse_part(raw)
    if part is None:
        return issues
    return [i.model_dump() for i in check(resolve(part, rules), rules)]


class Session:
    def __init__(self, runs_root: Path):
        self.runs_root = Path(runs_root)
        self.lock = threading.Lock()
        self._start()

    def _start(self) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.versions: list[Version] = []
        self.counter = 0
        self.preview_png: bytes | None = None

    @property
    def current(self) -> Version | None:
        return self.versions[-1] if self.versions else None

    @property
    def can_undo(self) -> bool:
        return len(self.versions) > 1

    def version_dir(self, number: int) -> Path:
        return self.runs_root / self.id / f"v{number}"

    def file_path(self, version: Version, kind: str) -> Path:
        """kind is "step", "dxf", "pdf" or "json"."""
        return self.version_dir(version.number) / version.summary["files"][kind]

    # --- Step 2: read ------------------------------------------------------------

    def read(self, data: bytes, filename: str, request: str, mode: str, rules: Rules) -> dict:
        """The AI reads the image. Nothing is built here.

        Raises reader.ReaderError (plain words) or NoPartYet."""
        if not data:
            raise reader.ReaderError("The uploaded file is empty.")
        if len(data) > MAX_UPLOAD:
            raise reader.ReaderError("The file is larger than 25 MB. Please upload a smaller image.")
        png = reader.to_png(data, filename)
        with self.lock:
            self.preview_png = png
            current = self.current

        if mode == "markup":
            if current is None:
                raise NoPartYet(
                    "There is no part to change yet. Create the part from its drawing first, then apply the markups."
                )
            result = reader.read_markup(data, png, request, current.part, rules)
            new_part, applied, problems = apply_changes(current.part, result["changes"])
            return {
                "mode": "markup",
                "source": result["source"],
                "draft": new_part.model_dump(),
                "uncertain": sorted({p for a in applied if a.uncertain for p in a.paths}),
                "changed": sorted({p for a in applied for p in a.paths}),
                "changes": [a.model_dump() for a in applied],
                "problems": problems,
                "filled": {},
                "notes": result["notes"],
            }
        result = reader.read_part(data, png, request, rules)
        return {"mode": "create", "changes": [], "changed": [], "problems": [], **result}

    # --- Steps 4 and 5: check and build ----------------------------------------------

    def apply(self, raw: dict, rules: Rules, how: str = "Edited by hand", build_anyway: bool = False) -> dict:
        """Check the confirmed values, then build all outputs.

        Returns {"built": bool, "issues": [...]} and, if a build failed, "error"."""
        part, issues = parse_part(raw)
        if part is None:
            return {"built": False, "issues": issues}
        part = resolve(part, rules)
        found = check(part, rules)
        dumped = [i.model_dump() for i in found]
        if any(i.severity == "error" for i in found) or (found and not build_anyway):
            return {"built": False, "issues": dumped}

        with self.lock:
            self.counter += 1
            number = self.counter
            try:
                summary = build_all(part, rules, self.version_dir(number))
            except Exception as exc:  # a build failure must not take the demo down
                self.counter -= 1
                shutil.rmtree(self.version_dir(number), ignore_errors=True)
                return {"built": False, "issues": dumped, "error": f"The part could not be built: {exc}"}
            how = how + (" (rules overridden)" if found else "")
            self.versions.append(Version(number=number, part=part, summary=summary, how=how))
        return {"built": True, "issues": dumped}

    def undo(self) -> bool:
        """Step back to the previous version. False if there is none."""
        with self.lock:
            if not self.can_undo:
                return False
            removed = self.versions.pop()
            shutil.rmtree(self.version_dir(removed.number), ignore_errors=True)
            return True

    def reset(self) -> None:
        with self.lock:
            shutil.rmtree(self.runs_root / self.id, ignore_errors=True)
            self._start()

    # --- Outputs -------------------------------------------------------------------------

    def zip_bytes(self, version: Version) -> bytes:
        """STEP, DXF, PDF and JSON of one version in a single ZIP."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in version.summary["files"].values():
                archive.write(self.version_dir(version.number) / name, arcname=name)
        return buffer.getvalue()
