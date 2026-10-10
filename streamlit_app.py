"""AI CAD Agent POC: the Streamlit app.

    uv run streamlit run streamlit_app.py

The same engine as the local web page (cadagent/app.py), with one working
session per browser session, so it can be hosted and used by several people.
Deployment: see docs/DEPLOYMENT.md.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="AI CAD Agent", page_icon="📐", layout="wide")

# Settings come from .env locally and from the app's Secrets when hosted. They
# must be in the environment before the reader module is imported.
load_dotenv(ROOT / ".env")
for _name in ("ANTHROPIC_API_KEY", "CADAGENT_MODEL", "APP_PASSWORD"):
    try:
        if _name in st.secrets and not os.environ.get(_name):
            os.environ[_name] = str(st.secrets[_name])
    except Exception:  # no secrets file at all
        break

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

from cadagent import reader  # noqa: E402
from cadagent.markup import field_label  # noqa: E402
from cadagent.models import Part, fmt  # noqa: E402
from cadagent.rules import Rules, RulesError  # noqa: E402
from cadagent.samples import TEST_DATA, available_samples  # noqa: E402
from cadagent.session import NoPartYet, Session, check_raw  # noqa: E402

RUNS = Path(tempfile.gettempdir()) / "cadagent_runs"
MODES = {"Create part": "create", "Apply markups": "markup"}
VIEWS = ["Uploaded sheet", "3D view", "Flat pattern", "Drawing sheet", "Part data"]
NO_SAMPLE = "None"
HOLE_COLUMNS = {"flange": "Flange", "from_edge": "From edge", "from_left": "From left", "diameter": "Ø"}
STYLE = """
<style>
  .block-container { padding-top: 4rem; }
  /* Keep the sheet and the outputs in view while the numbers are checked. */
  @media (min-width: 900px) {
    .st-key-outputs, div:has(> .st-key-outputs) { position: sticky; top: 4rem; }
  }
</style>
"""
UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "webp", "heic", "heif"]


# --- Session state ---------------------------------------------------------------


def require_password() -> None:
    """Optional gate for a hosted demo: set APP_PASSWORD in the app's Secrets."""
    expected = os.environ.get("APP_PASSWORD")
    if not expected or st.session_state.get("unlocked"):
        return
    st.title("AI CAD Agent")
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Open the demo", type="primary"):
            if hmac.compare_digest(entered.encode(), expected.encode()):
                st.session_state.unlocked = True
                st.rerun()
            st.error("That password is not correct.")
    st.stop()


def clean_old_runs(max_age_hours: float = 24) -> None:
    """Outputs of sessions that ended long ago are removed from the server."""
    if not RUNS.exists():
        return
    cutoff = time.time() - max_age_hours * 3600
    for folder in RUNS.iterdir():
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def init_state() -> None:
    if "session" in st.session_state:
        return
    clean_old_runs()
    st.session_state.session = Session(RUNS)
    st.session_state.mode = "Create part"
    st.session_state.sample = NO_SAMPLE
    st.session_state.request = ""
    st.session_state.view = "3D view"
    st.session_state.upload_gen = 0
    clear_draft()


def clear_draft() -> None:
    st.session_state.draft = None
    st.session_state.meta = None
    st.session_state.how = "Edited by hand"
    st.session_state.gen = st.session_state.get("gen", 0) + 1


def adopt_current_part() -> None:
    """Show the current part in the form, ready for editing by hand."""
    current = st.session_state.session.current
    clear_draft()
    if current:
        st.session_state.draft = current.part.model_dump()


def on_sample_change() -> None:
    sample = next((s for s in available_samples() if s["label"] == st.session_state.sample), None)
    if sample:
        st.session_state.mode = next(k for k, v in MODES.items() if v == sample["mode"])
        st.session_state.request = sample["request"]


# --- Step 1: upload and ask ----------------------------------------------------------


def step_upload(session: Session, rules: Rules) -> None:
    st.markdown("#### 1 · Upload and ask")
    mode_label = st.radio("What should the demo do?", list(MODES), horizontal=True, key="mode")
    mode = MODES[mode_label]
    needs_part = mode == "markup" and session.current is None
    if needs_part:
        st.info("Markups change an existing part. Create the part from its drawing first.")
    elif mode == "markup":
        st.caption("Upload a photo of the printed drawing with hand markups. The changes are applied to the current part.")
    else:
        st.caption("Upload a drawing or a hand sketch of one part. The AI reads the numbers and you check them before anything is built.")

    upload = st.file_uploader(
        "Drawing, marked-up print or sketch", type=UPLOAD_TYPES, key=f"upload_{st.session_state.upload_gen}",
        help="PDF, PNG, JPEG or a phone photo. Only the first page of a PDF is read.",
    )
    samples = available_samples()
    if samples:
        st.selectbox(
            "…or use a test file", [NO_SAMPLE] + [s["label"] for s in samples], key="sample",
            on_change=on_sample_change, help="The placeholder test files that come with the demo.",
        )
    sample = next((s for s in samples if s["label"] == st.session_state.sample), None)

    st.text_input(
        "Your request", key="request",
        placeholder="Apply the markups" if mode == "markup" else "Create this part",
    )

    if upload is not None:
        data, filename = upload.getvalue(), upload.name
    elif sample:
        data, filename = (TEST_DATA / sample["file"]).read_bytes(), Path(sample["file"]).name
    else:
        data, filename = None, ""
    if data is not None:
        st.caption(f"Ready to read: **{filename}**")

    if st.button("Read", type="primary", disabled=data is None or needs_part, width="stretch"):
        st.session_state.pop("read_error", None)
        try:
            with st.spinner("The AI is reading the image…" if reader.ai_available() else "Reading…"):
                result = session.read(data, filename, st.session_state.request, mode, rules)
        except (reader.ReaderError, NoPartYet) as exc:
            st.session_state.read_error = str(exc)
        else:
            clear_draft()
            st.session_state.draft = result["draft"]
            st.session_state.meta = result
            st.session_state.how = f"{'Markups from' if mode == 'markup' else 'Read from'} {filename}"
            st.session_state.view = "Uploaded sheet"
        st.rerun()
    if st.session_state.get("read_error"):
        st.error(st.session_state.read_error)


# --- Step 2: check the numbers --------------------------------------------------------


def step_confirm(session: Session, rules: Rules) -> None:
    draft = st.session_state.draft
    if draft is None:
        return
    meta = st.session_state.meta or {}
    gen = st.session_state.gen
    uncertain, changed, filled = set(meta.get("uncertain", [])), set(meta.get("changed", [])), meta.get("filled", {})

    st.divider()
    st.markdown("#### 2 · Check the numbers")
    if meta.get("mode") == "markup":
        st.caption("These are the current values with the markups applied. Correct anything that is wrong, then apply.")
    elif meta:
        st.caption("Compare with the uploaded sheet on the right, correct anything that is wrong, then apply.")
    else:
        st.caption("This is the current part. Change any value and apply to rebuild it.")
    if meta.get("notes"):
        (st.info if meta.get("source") == "ai" else st.warning)(meta["notes"])
    if meta.get("mode") == "markup":
        with st.container(border=True):
            st.markdown("**Changes found** · was → now")
            for change in meta["changes"]:
                flag = " ⚠️ *check*" if change["uncertain"] else ""
                quote = f" — *“{change['markup_text']}”*" if change["markup_text"] else ""
                st.markdown(f"- **{change['label']}**{flag}{quote}")
            for problem in meta["problems"]:
                st.markdown(f"- :red[{problem}]")
            if not meta["changes"] and not meta["problems"]:
                st.markdown("- No changes were found in this image.")

    def label(path: str, text: str, value) -> str:
        """Mark a value until the engineer has edited it."""
        untouched = value == draft.get(path)
        if path in uncertain and untouched:
            return f"{text} ⚠️ check"
        if path in changed and untouched:
            return f"{text} ✏️ changed"
        return text

    def number(path: str, text: str, column, **kwargs) -> float | None:
        key = f"{path}_{gen}"
        current = st.session_state.get(key, draft.get(path))
        start = draft.get(path)
        return column.number_input(
            label(path, text, current), value=None if start is None else float(start), min_value=0.0, step=1.0, format="%g",
            key=key, help=filled.get(path), **kwargs,
        )

    left, right = st.columns(2)
    types = ["plate", "l_bracket"]
    type_key = f"part_type_{gen}"
    part_type = left.selectbox(
        label("part_type", "Part type", st.session_state.get(type_key, draft["part_type"])), types,
        index=types.index(draft["part_type"]), key=type_key,
        format_func={"plate": "Flat plate", "l_bracket": "L-bracket"}.get,
    )
    bracket = part_type == "l_bracket"
    name_key = f"name_{gen}"
    name = right.text_input(label("name", "Name", st.session_state.get(name_key, draft.get("name") or "")), value=draft.get("name") or "", key=name_key)

    materials = rules.material_names()
    if draft.get("material") and draft["material"] not in materials:
        materials = materials + [draft["material"]]
    material_key = f"material_{gen}"
    material = left.selectbox(
        label("material", "Material", st.session_state.get(material_key, draft.get("material"))), materials,
        index=materials.index(draft["material"]) if draft.get("material") in materials else 0,
        key=material_key, help=filled.get("material"),
    )
    thickness = number("thickness", "Thickness (mm)", right)
    if allowed := ", ".join(fmt(t) for t in rules.thicknesses(material)):
        st.caption(f"Allowed thicknesses for {material}: {allowed} mm")
    left, right = st.columns(2)
    width = number("width", "Width (mm, along the bend)" if bracket else "Width (mm)", left)
    flange_a = number("flange_a", "Flange A (mm, outside)" if bracket else "Length (mm)", right)
    flange_b = bend_radius = None
    if bracket:
        left, right = st.columns(2)
        flange_b = number("flange_b", "Flange B (mm, outside)", left)
        bend_radius = number("bend_radius", "Inner bend radius (mm)", right, placeholder="from the rules table")

    # --- Holes ---
    st.markdown("**Holes**")
    edge_title = "From free edge" if bracket else "From bottom"
    edge_column = "Free edge" if bracket else "Bottom"
    st.caption(
        f"One row per hole, numbered in order. **{edge_column}** = distance {edge_title.lower()} and **Left** = "
        "distance from the left side, both to the hole centre, in mm. "
        "Add a hole in the empty row at the bottom; to remove one, tick its row and press Delete."
    )
    holes_df = pd.DataFrame(
        [{c: h.get(c) for c in HOLE_COLUMNS} for h in draft.get("holes", [])], columns=list(HOLE_COLUMNS)
    ).astype({"from_edge": "float64", "from_left": "float64", "diameter": "float64"})
    holes_df.insert(0, "hole", [f"H{i + 1}" for i in range(len(holes_df))])
    edited = st.data_editor(
        holes_df, key=f"holes_{gen}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "hole": st.column_config.TextColumn("Hole", disabled=True, width=50),
            "flange": st.column_config.SelectboxColumn("Flange", options=["A", "B"], default="A", required=True, width="small") if bracket else None,
            "from_edge": st.column_config.NumberColumn(edge_column, min_value=0.0, width="small", help=f"{edge_title}, to the hole centre (mm)"),
            "from_left": st.column_config.NumberColumn("Left", min_value=0.0, width="small", help="From the left side, to the hole centre (mm)"),
            "diameter": st.column_config.NumberColumn("Ø", min_value=0.0, width="small"),
        },
    )
    holes = []
    for row in edited.to_dict("records"):
        hole = {c: (None if pd.isna(row[c]) else float(row[c])) for c in ("from_edge", "from_left", "diameter")}
        if all(v is None for v in hole.values()):
            continue  # an empty row that was added but not filled in
        flange = row.get("flange")
        holes.append({"flange": flange if bracket and flange in ("A", "B") else "A", **hole})

    def hole_marks(paths: set[str]) -> list[str]:
        out = []
        new = {i for i in range(len(holes)) if all(f"holes.{i}.{f}" in paths for f in HOLE_COLUMNS)}
        out += [f"Hole {i + 1} (new)" for i in sorted(new)]
        for path in sorted(paths):
            match = re.fullmatch(r"holes\.(\d+)\.(\w+)", path)
            if not match or int(match[1]) in new:
                continue
            i, field = int(match[1]), match[2]
            original = draft["holes"][i].get(field) if i < len(draft["holes"]) else None
            if i < len(holes) and holes[i].get(field) == original:
                word = {"diameter": "Ø", "flange": "flange"}.get(field) or field_label(Part.model_construct(part_type=part_type), field)
                out.append(f"Hole {i + 1} {word}")
        return out

    if marks := hole_marks(uncertain):
        st.caption("⚠️ Check: " + ", ".join(marks))
    if marks := hole_marks(changed):
        st.caption("✏️ Changed by markup: " + ", ".join(marks))

    raw = {
        "part_type": part_type, "name": name, "material": material, "thickness": thickness, "width": width,
        "flange_a": flange_a, "flange_b": flange_b, "bend_radius": bend_radius, "holes": holes,
    }

    # --- Rule check, live ---
    issues = check_raw(raw, rules)
    errors = [i for i in issues if i["severity"] == "error"]
    rule_breaks = [i for i in issues if i["severity"] == "rule"]
    for issue in errors:
        st.error(issue["message"], icon="⛔")
    for issue in rule_breaks:
        st.warning(issue["message"], icon="⚠️")
    if not issues:
        st.success("All engineering rules pass.", icon="✅")

    apply_col, force_col = st.columns(2)
    clicked = apply_col.button("Apply and build", type="primary", disabled=bool(issues), width="stretch")
    forced = False
    if rule_breaks and not errors:
        forced = force_col.button(
            "Build anyway", width="stretch",
            help="Build the part even though it breaks an engineering rule. This is recorded in the version history.",
        )
    if clicked or forced:
        with st.spinner("Building the 3D part, flat pattern and drawing…"):
            result = session.apply(raw, rules, how=st.session_state.how, build_anyway=forced)
        if result["built"]:
            adopt_current_part()
            st.session_state.view = "3D view"
            st.session_state.flash = f"Built {session.current.part.name or 'the part'} · version {len(session.versions)}"
            st.rerun()
        st.error(result.get("error") or "Not built. Fix the problems listed above.")


# --- Outputs -----------------------------------------------------------------------------


def figure_3d(mesh: dict) -> go.Figure:
    pos, idx = mesh["positions"], mesh["indices"]
    figure = go.Figure(go.Mesh3d(
        x=pos[0::3], y=pos[1::3], z=pos[2::3], i=idx[0::3], j=idx[1::3], k=idx[2::3],
        color="#b9c3d0", flatshading=False, hoverinfo="skip",
        lighting=dict(ambient=0.55, diffuse=0.75, specular=0.25, roughness=0.5, fresnel=0.1),
        lightposition=dict(x=-400, y=-900, z=1200),
    ))
    ex, ey, ez = [], [], []
    for line in mesh["edges"]:
        ex += line[0::3] + [None]
        ey += line[1::3] + [None]
        ez += line[2::3] + [None]
    figure.add_trace(go.Scatter3d(x=ex, y=ey, z=ez, mode="lines", line=dict(color="#1f2937", width=3), hoverinfo="skip"))
    hidden = dict(visible=False)
    figure.update_layout(
        scene=dict(xaxis=hidden, yaxis=hidden, zaxis=hidden, aspectmode="data",
                   camera=dict(eye=dict(x=-1.25, y=-1.75, z=1.25), up=dict(x=0, y=0, z=1))),
        margin=dict(l=0, r=0, t=0, b=0), height=430, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return figure


def outputs(session: Session, rules: Rules) -> None:
    current = session.current
    view = st.segmented_control("View", VIEWS, key="view", label_visibility="collapsed") or "3D view"

    if view == "Uploaded sheet":
        if session.preview_png:
            st.image(session.preview_png, width="stretch")
        else:
            st.info("Upload a file to see it here, next to the numbers.")
        return
    if current is None:
        st.info("Nothing built yet. Upload a drawing, check the numbers, then click **Apply and build**.")
        return

    folder = session.version_dir(current.number)
    derived = current.summary["derived"]
    facts = [
        f"**{current.part.name or 'Part'}**",
        f"Flat length **{fmt(derived['flat_length_mm'])} mm**",
        f"Flat size **{fmt(derived['flat_size_mm'][0])} × {fmt(derived['flat_size_mm'][1])} mm**",
    ]
    if "k_factor" in derived:
        facts.append(f"K-factor **{fmt(derived['k_factor'])}**")
    st.markdown(" &nbsp;·&nbsp; ".join(facts))

    if view == "3D view":
        st.plotly_chart(figure_3d(json.loads((folder / "mesh.json").read_text())), width="stretch", config={"displaylogo": False})
        st.caption("Drag to rotate · scroll to zoom · right-drag to pan")
    elif view == "Flat pattern":
        svg = (folder / "flat.svg").read_text().replace("currentColor", "#1b2430")
        # A bracket's flat pattern is tall and narrow: size it by height, not page width.
        wide = derived["flat_size_mm"][0] > derived["flat_size_mm"][1] * 1.2
        st.image(svg.replace("<svg ", '<svg style="background:#ffffff" ', 1), width="stretch" if wide else 330)
        expected = st.number_input(
            "Expected flat length (mm), to compare", value=None, min_value=0.0, format="%g", key=f"expected_{current.number}",
            help="Your own calculation or CAD value. The tolerance comes from the rules file.",
        )
        if expected is not None:
            difference = derived["flat_length_mm"] - expected
            text = f"Difference {difference:+.2f} mm (tolerance ±{fmt(rules.flat_length_tolerance)} mm)"
            if abs(difference) <= rules.flat_length_tolerance + 1e-9:
                st.success(f"Matches. {text}", icon="✅")
            else:
                st.error(f"Does not match. {text}", icon="⛔")
    elif view == "Drawing sheet":
        st.image(str(folder / "sheet.png"), width="stretch")
    else:
        st.json(current.summary["part_json"])

    st.markdown("**Download**")
    columns = st.columns(5)
    files = [("step", "STEP", "model/step"), ("dxf", "DXF", "image/vnd.dxf"), ("pdf", "PDF", "application/pdf"), ("json", "JSON", "application/json")]
    for column, (kind, text, mime) in zip(columns, files):
        path = session.file_path(current, kind)
        column.download_button(text, path.read_bytes(), file_name=path.name, mime=mime, width="stretch", key=f"dl_{kind}_{current.number}")
    stem = session.file_path(current, "step").stem
    columns[4].download_button(
        "ZIP (all)", session.zip_bytes(current), file_name=f"{stem}_v{len(session.versions)}.zip",
        mime="application/zip", width="stretch", key=f"dl_zip_{current.number}",
    )


def sidebar(session: Session) -> None:
    with st.sidebar:
        st.markdown("### 📐 AI CAD Agent")
        st.caption("Drawing, markup or sketch → sheet-metal part")
        if reader.ai_available():
            st.success(f"AI reading is on\n\n`{reader.MODEL}`")
        else:
            st.warning("**Offline demo mode**\n\nNo AI key is set. The test files are read from the answer key; other files give an empty form.")
        st.divider()
        st.markdown("**Versions**")
        if not session.versions:
            st.caption("No part built yet.")
        for i, version in enumerate(session.versions, start=1):
            marker = "🔵" if version is session.current else "⚪"
            st.markdown(f"{marker} **v{i}** · {version.part.name or 'Part'}  \n<small>{version.how}</small>", unsafe_allow_html=True)
        if st.button("↶ Undo", disabled=not session.can_undo, width="stretch", help="Step back to the previous version of the part."):
            session.undo()
            adopt_current_part()
            st.session_state.flash = f"Back to version {len(session.versions)}"
            st.rerun()
        if st.button("New part", width="stretch", help="Clear everything and start again."):
            session.reset()
            clear_draft()
            st.session_state.upload_gen += 1
            st.session_state.sample = NO_SAMPLE
            st.session_state.request = ""
            st.session_state.mode = "Create part"
            st.session_state.view = "3D view"
            st.session_state.pop("read_error", None)
            st.rerun()


# --- Guide pages ---------------------------------------------------------------------------


def render_markdown(path: Path) -> None:
    """Markdown with local images (st.markdown cannot show those itself)."""
    if not path.exists():
        st.info(f"{path.name} is missing.")
        return
    block: list[str] = []
    for line in path.read_text().splitlines():
        image = re.fullmatch(r"!\[(.*?)\]\((.+?)\)", line.strip())
        if not image:
            block.append(line)
            continue
        if block:
            st.markdown("\n".join(block))
            block = []
        target = path.parent / image[2]
        if target.exists():
            st.image(str(target), caption=image[1] or None)
    if block:
        st.markdown("\n".join(block))


# --- Page -------------------------------------------------------------------------------------


def main() -> None:
    require_password()
    init_state()
    session: Session = st.session_state.session
    try:
        rules = Rules.load()
    except RulesError as exc:
        st.error(str(exc))
        st.stop()
    if flash := st.session_state.pop("flash", None):
        st.toast(flash, icon="✅")

    st.html(STYLE)
    sidebar(session)
    demo, guide, features = st.tabs(["Demo", "How to use", "Features and limitations"])
    with demo:
        left, right = st.columns([6, 7], gap="large")
        with left:
            step_upload(session, rules)
            step_confirm(session, rules)
        with right, st.container(key="outputs"):
            outputs(session, rules)
    with guide:
        render_markdown(ROOT / "docs" / "USER_GUIDE.md")
    with features:
        render_markdown(ROOT / "docs" / "FEATURES.md")
        render_markdown(ROOT / "KNOWN_LIMITATIONS.md")


main()
