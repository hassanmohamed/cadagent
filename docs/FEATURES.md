# Features

What the demo does today. Limitations are listed after this section.

## The three scenarios

| Scenario | Input | Result |
|---|---|---|
| 1. Drawing to part | A drawing of one part (PDF or image) | The part data, checked by the engineer, then all outputs |
| 2. Markup to change | A photo of the printed drawing with hand markups | Each change listed as *was → now*, applied to the current part as a new version |
| 3. Sketch to part | A photo of a hand sketch with written dimensions | Same flow as scenario 1 |

Supported parts: flat plate and L-bracket with one 90° bend, with round holes.

## Reading

- **AI reading** of drawings, markup photos and sketches. The AI returns only numbers in a
  fixed form; it never produces geometry.
- **Uncertain values are flagged.** The AI lists the values it could not read with
  confidence, and these are marked ⚠️ check in the form.
- **Missing values use the rules table.** If material or thickness is not on the sheet,
  the default is filled in and flagged. If the bend radius is not shown, the one for that
  material and thickness is used.
- **Markup changes** are reported per hole and per value: diameter, position, flange, a
  hole added or removed, or a changed part value such as thickness. Each change shows the
  handwriting it was read from.
- **Material names are normalised**: "S235" on a drawing becomes "Steel S235" from the
  rules table.
- **File types**: PDF (first page), PNG, JPEG, WEBP, and HEIC phone photos. Up to 25 MB.
- **Offline demo mode**: without an AI key, the bundled test files are filled in from the
  answer key so the rest of the flow can still be shown.

## Checking

- **Editable confirmation form** with the uploaded sheet shown next to it.
- **Live rule check**: every edit is checked at once, and problems are written in plain
  words, e.g. "Hole 2 is too close to the bend: 1.5 mm, minimum 6 mm."
- **Two kinds of problem.** A broken engineering rule can be overridden with *Build
  anyway*, and the override is recorded in the version history. Impossible geometry, such
  as a hole running into the bend or off the part, cannot be built.

| Check | Kind |
|---|---|
| Material is in the rules table | Cannot build |
| Thickness is allowed for the material | Cannot build |
| A value is missing or not a number | Cannot build |
| Flange is long enough to bend (longer than radius + thickness) | Cannot build |
| Hole lies fully on its flange and clear of the bend zone | Cannot build |
| Two holes overlap | Cannot build |
| Bend radius differs from the rules table | Rule |
| Hole smaller than the minimum diameter | Rule |
| Hole too close to an edge | Rule |
| Hole too close to the bend | Rule |
| Two holes too close together | Rule |

## Building

- **3D part** from fixed templates, checked against a hand-calculated volume on every
  build.
- **Flat pattern** unfolded with the K-factor method:
  `L = A + B − 2(r + t) + (π/2)(r + k·t)`.
- **Flat length comparison**: type your expected value to see whether it matches within
  the tolerance from the rules file.

| Output | File | Contents |
|---|---|---|
| 3D view | on screen | Rotate, zoom, pan |
| STEP | `<name>.step` | The 3D model |
| Flat pattern | `<name>_flat.dxf` | Outline, holes, bend line and main dimensions on separate layers (`OUTLINE`, `HOLES`, `BEND`, `DIMENSIONS`, `TEXT`), in mm |
| Drawing sheet | `<name>_drawing.pdf` | A3: front, top and side views, flat pattern, key dimensions, hole table, notes, title block, one-row parts list |
| Part data | `<name>.json` | The part values plus flat length, flat size, K-factor, bend allowance and rules version |
| Everything | `<name>_vN.zip` | The four files above |

## Working with versions

- Every build is a new **version**, labelled with what produced it.
- **Undo** steps back one version. **New part** starts again.
- Values can be **edited by hand** at any time and the part rebuilt.

## Engineering rules file

- All rules live in one readable file, `rules/rules.yaml`: materials and their aliases,
  allowed thicknesses, bend radius and K-factor per material and thickness, default
  material and thickness, the four limits, and the flat length tolerance.
- Each limit is the larger of a fixed value in mm and a multiple of the thickness.
- The file is read on every action, so an edit takes effect without restarting.
- A mistake in the file is reported in plain words, e.g. "Problem in rules.yaml:
  material "Steel S235", thickness 3: k_factor must be between 0 and 1, but is 44."

## Two ways to run it

| | Streamlit app | Local web page |
|---|---|---|
| Start | `uv run streamlit run streamlit_app.py` | `./run.sh` |
| Use | Hosted for several people, or on a laptop | One person on a laptop |
| Sessions | One per browser session | One shared |
| Password | Optional | None |
| Built-in guide | Yes | No |
| Flat length comparison | Yes | No |

Both use the same engine, so reading, rules and outputs are identical.

## For acceptance testing

- `tools/score_reading.py` runs the AI over every test file and compares the result with
  the answer key: each value must be read correctly or flagged as uncertain.
- 51 automated tests cover the flat length formula, every rule, the 3D geometry, the
  STEP, DXF and PDF files, both scenarios run five times in a row, and the Streamlit app.
