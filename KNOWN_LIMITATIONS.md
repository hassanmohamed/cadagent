# Known limitations and open checks

## Not yet done or not yet verified

- **AI reading is untested against the live AI.** No API key was available during
  development. The request sent to the AI and the handling of its answer are covered by
  tests with a stand-in, but the prompts have not been tuned and the reading has not been
  scored on any file. Run `uv run python tools/score_reading.py` once a key is in `.env`.
- **All engineering content is placeholder.** The materials, thicknesses, bend radii,
  K-factors and limits in `rules/rules.yaml` are typical textbook values, not the
  company's. Flat lengths are therefore not validated against the domain expert's
  expected values.
- **The test files are synthetic.** The two drawings come from the demo's own drawing
  generator, and the markup "photos" and the sketch are computer-made imitations. Real
  scans, real handwriting and real phone photos will be harder for the AI to read.
- **The STEP file has not been opened in Inventor.** It is re-imported in the tests and
  matches the part's volume and size, but the acceptance check in Inventor is still open.
- **The hosted (Linux) install has not been run.** The Streamlit app is tested on a Mac.
  For Streamlit Community Cloud it is confirmed that every package has a ready-made
  Linux build for Python 3.12, and which system libraries the CAD kernel needs
  (`packages.txt`), but the app has not been started on a Linux server yet. The CAD
  kernel is large (about 1.7 GB installed, about 550 MB of memory in use), which may be
  tight on a free hosting tier.
- **Timing with the AI is unmeasured.** Offline, a scenario takes seconds. With the AI,
  reading should add well under a minute per image.

## By design (out of scope for the POC)

- Parts: flat plate and L-bracket with one 90° bend, round holes only. No U-channel,
  no slots, no cut-outs, no chamfers or corner radii.
- No assemblies, welded plates, weld symbols, GD&T or tolerances.
- No connection to Inventor or other CAD software; the STEP file and `part.json` are
  the hand-over.
- One part at a time per session. The local web page has a single session shared by
  everyone who opens it; the Streamlit app gives each browser session its own. State is
  kept in memory: restarting the server, or reloading the Streamlit page, clears the
  current part and the undo history.
- Undo steps back one version at a time and discards the undone version; there is no redo.
- Only the first page of a PDF is read.

## Things to know

- **The drawings must follow the dimension conventions** in the README. A drawing
  dimensioned differently (for example inside flange lengths, or holes measured from the
  bend) will be read wrongly unless the AI notices and flags it.
- **"From the left side"** means left as drawn in the top view and flat pattern, with
  Flange A's free edge at the bottom. The domain expert should confirm this matches
  their drawings, especially for holes on Flange B.
- **A plate is laid out with its length (Flange A) horizontal**, and its holes measured
  up from the bottom edge and along from the left edge.
- **Markups are applied to the current part.** Scenario 2 needs the part to exist first
  (scenario 1). Hole numbers in a markup refer to the hole table of the current part.
- **The hole table on the sheet shows at most 9 holes**; the rest are in `part.json`.
- **The drawing sheet is simple**: overall dimensions and a hole table rather than full
  dimensioning, no hidden lines, no section views.
- **Rule violations can be overridden** with *Build anyway* (recorded in the version
  history); geometry that cannot exist, such as a hole running into the bend, cannot.
- **Offline demo mode** recognises the bundled test files by their exact content. A
  re-saved or edited copy is treated as an unknown file.
- **Images are sent to Anthropic's API** when AI reading is on, and a hosted Streamlit
  app runs on a third party's servers. Check this against company policy before uploading
  confidential drawings.
- **The hosted app's password is a single shared password**, not user accounts.
- **In the Streamlit holes table**, the hole number of a newly added row appears only
  after the part is built.
- The flat pattern uses one K-factor per material and thickness; it does not vary with
  bend radius or tooling.
