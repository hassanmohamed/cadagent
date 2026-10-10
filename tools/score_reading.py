"""Score the AI reading against the answer key (Day 3 of the plan).

    uv run python tools/score_reading.py

Needs ANTHROPIC_API_KEY (in the environment or in .env). Every value must be
read correctly or flagged as uncertain. Each run calls the AI once per test
file, which costs a few cents in total.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from cadagent import reader  # noqa: E402
from cadagent.markup import apply_changes  # noqa: E402
from cadagent.models import Part  # noqa: E402
from cadagent.rules import Rules  # noqa: E402

TEST_DATA = ROOT / "test_data"


def flatten(part: dict) -> dict[str, object]:
    flat = {k: v for k, v in part.items() if k != "holes"}
    for i, hole in enumerate(part.get("holes") or []):
        for key, value in hole.items():
            flat[f"holes.{i}.{key}"] = value
    return flat


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-6
    return a == b


def score(expected: dict, got: dict, uncertain: set[str]) -> tuple[int, int, int, list[str]]:
    """Returns (correct, flagged, wrong, descriptions of wrong values)."""
    want, have = flatten(expected), flatten(got)
    correct = flagged = wrong = 0
    misses = []
    for path in sorted(set(want) | set(have)):
        if same(want.get(path), have.get(path)):
            correct += 1
        elif path in uncertain:
            flagged += 1
        else:
            wrong += 1
            misses.append(f"{path}: expected {want.get(path)!r}, read {have.get(path)!r}")
    return correct, flagged, wrong, misses


def main() -> int:
    if not reader.ai_available():
        print("No AI key found. Put ANTHROPIC_API_KEY in .env (see .env.example) and run again.")
        return 2
    rules = Rules.load()
    key = json.loads((TEST_DATA / "answer_key.json").read_text())["files"]
    failed = False
    for name, entry in key.items():
        data = (TEST_DATA / name).read_bytes()
        png = reader.to_png(data, name)
        try:
            if entry["kind"] == "markup":
                base = Part.model_validate(key[f"drawings/{entry['base']}.pdf"]["part"])
                result = reader.read_markup(data, png, "Apply the markups", base, rules)
                new, applied, problems = apply_changes(base, result["changes"])
                uncertain = {p for a in applied if a.uncertain for p in a.paths}
                correct, flagged, wrong, misses = score(entry["expected_part"], new.model_dump(), uncertain)
                misses += problems
                detail = "; ".join(a.label for a in applied) or "no changes found"
            else:
                result = reader.read_part(data, png, "Create this part", rules)
                correct, flagged, wrong, misses = score(entry["part"], result["draft"], set(result["uncertain"]))
                detail = result["notes"]
        except reader.ReaderError as exc:
            print(f"FAIL  {name}\n      {exc}")
            failed = True
            continue
        ok = wrong == 0 and not misses
        failed |= not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {correct} correct, {flagged} flagged as uncertain, {wrong} wrong")
        if detail:
            print(f"      {detail}")
        for miss in misses:
            print(f"      WRONG {miss}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
