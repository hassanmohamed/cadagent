# AI CAD Agent POC

A demo for management: an AI reads an engineering drawing, a marked-up print or a hand
sketch and the software produces the sheet-metal part, its flat pattern and a basic
drawing. Pure Python, no CAD software needed.

The AI only reads the numbers. The software builds the part from fixed templates, and
nothing is built until the engineer has checked the numbers.

> **Status.** The test drawings, markups, sketch, answer key and every value in
> `rules/rules.yaml` are **placeholders made by the developer** so the demo could be
> built and tested. They must be replaced with the domain expert's inputs. The AI
> reading has not yet been run against a live AI key. See
> [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

| Document | For | What it covers |
|---|---|---|
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Domain expert | Step-by-step use of the demo, with screenshots |
| [docs/FEATURES.md](docs/FEATURES.md) | Everyone | What the demo does |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | Everyone | What it does not do, and what is not yet verified |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Developer | Hosting the Streamlit app |

## Setup

You need a Mac, Windows or Linux laptop with [uv](https://docs.astral.sh/uv/) installed.

```sh
uv sync                 # installs Python 3.12 and all dependencies (first run takes a few minutes)
cp .env.example .env    # then put your Anthropic API key in .env
```

There are two front ends on the same engine. Use whichever suits the occasion:

```sh
uv run streamlit run streamlit_app.py   # Streamlit app, http://localhost:8501 (can be hosted)
./run.sh                                # local web page, http://localhost:8000 (one laptop, one user)
```

On Windows, start the local page with `uv run uvicorn cadagent.app:app --port 8000`.
The Streamlit app has the built-in guide, an optional password and the flat length
comparison; the local page has a smoother 3D view. To host the Streamlit app, see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Without an API key the demo still runs, in **offline demo mode**: the five bundled test
files are "read" from the answer key, and any other file gives an empty form to fill in
by hand. The badge at the top right of the page shows which mode is active.

## Running the demo

The full walk-through is in [docs/USER_GUIDE.md](docs/USER_GUIDE.md). In short:

1. Click a test file (or drop your own PDF, PNG, JPEG or phone photo), type a request
   and click **Read**.
2. Check the numbers against the sheet shown on the right. Values the AI was not sure
   about are highlighted amber. For markups, each change is listed as *was → now*.
3. Click **Apply and build**. The part is checked against the engineering rules;
   problems are reported in plain words. A rule violation can be overridden with
   **Build anyway**; impossible geometry cannot.
4. Look at the 3D view, flat pattern and drawing sheet, and download the files.
5. **Undo** steps back to the previous version of the part.

| Scenario | Do this |
|---|---|
| 1. Drawing to part | *Plate drawing* or *L-bracket drawing* → Read → Apply and build |
| 2. Markup to change | After scenario 1, *Plate markup* or *L-bracket markup* → Read → Apply and build |
| 3. Sketch to part | *Hand sketch* → Read → check the highlighted value → Apply and build |

## Outputs

| Output | File | Used for |
|---|---|---|
| 3D view | on screen | Visual check |
| STEP | `<name>.step` | Opening in Inventor, SolidWorks or Fusion |
| Flat pattern | `<name>_flat.dxf` | Laser cutting. Layers: `OUTLINE`, `HOLES`, `BEND`, `DIMENSIONS`, `TEXT` |
| Drawing sheet | `<name>_drawing.pdf` | Review: front, top and side views, flat pattern, hole table, title block, parts list |
| Part data | `<name>.json` | The numbers behind the part; the link to future CAD integration |

A **ZIP** download bundles the four files. On the local page every version's files are
kept under `runs/` until **New part** or **Undo**; the Streamlit app uses the system
temporary folder.

## Dimension conventions

- All dimensions are in mm.
- Flange lengths are outside dimensions. The L-bracket bend angle is 90°.
- Width is the size along the bend line. For a plate, Flange A is its length.
- L-bracket holes are measured from the free edge of their flange and from the left side.
- Plate holes are measured from the bottom-left corner.
- Hole sizes are diameters.
- Flat length: `L = A + B − 2(r + t) + (π/2)(r + k·t)`.

## For the domain expert

- **Rules**: edit `rules/rules.yaml`. It is read on every request, so changes take
  effect without restarting.
- **Test files**: put them in `test_data/` and list the correct values in
  `test_data/answer_key.json` (same shape as the placeholder entries).
- **Score the AI reading** against the answer key:
  `uv run python tools/score_reading.py`. Every value must be read correctly or
  flagged as uncertain.

## For the developer

```sh
uv run pytest                           # 51 tests, no AI key needed
uv run python tools/make_test_data.py   # regenerate the placeholder test files (macOS)
```

| Path | What it is |
|---|---|
| `cadagent/models.py` | Part data: the contract between AI, form, rules and geometry |
| `cadagent/rules.py` | Loads `rules/rules.yaml`; rule checks in plain words |
| `cadagent/flat.py` | K-factor unfolding |
| `cadagent/geometry.py` | Plate and L-bracket templates (CadQuery), STEP, mesh for the 3D view |
| `cadagent/dxf_export.py`, `cadagent/sheet.py` | Flat pattern DXF and drawing sheet PDF |
| `cadagent/reader.py` | AI reading (Claude vision with structured output) and the offline fallback |
| `cadagent/markup.py` | Applies markup changes and describes them as *was → now* |
| `cadagent/session.py` | One working session: read, check, build, undo. Used by both front ends |
| `streamlit_app.py` | The Streamlit app |
| `cadagent/app.py`, `cadagent/static/` | The local web page and its server |
| `requirements.txt`, `packages.txt`, `.streamlit/` | Used when the Streamlit app is hosted |
