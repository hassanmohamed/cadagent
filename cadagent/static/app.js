// AI CAD Agent POC: the demo screen.
// upload -> read -> confirm -> apply -> view -> download -> undo
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const NUMBER_FIELDS = ["thickness", "width", "flange_a", "flange_b", "bend_radius"];
const HOLE_FIELDS = ["from_edge", "from_left", "diameter"];
const MODE_HINTS = {
  create: "Upload a drawing or a hand sketch of one part. The AI reads the numbers and you check them before anything is built.",
  markup: "Upload a photo of the printed drawing with hand markups. The changes are applied to the current part.",
};
const MARKUP_WORDS = /mark-?up|change|update|modif|revis/i;

const ui = {
  server: null,        // last /api/state payload
  mode: "create",
  file: null,
  draft: null,         // the values in the confirmation form
  uncertain: new Set(),
  changed: new Set(),
  filled: {},
  issues: [],
  how: "Edited by hand",
  shownVersion: null,
};

// --- Server -------------------------------------------------------------------

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Could not reach the demo server. Is it still running?");
  }
  let body = null;
  try { body = await response.json(); } catch { /* not JSON */ }
  if (!response.ok && !(body && "issues" in body)) {
    throw new Error((body && body.error) || `The server reported an error (${response.status}).`);
  }
  return body;
}

const postJson = (path, data) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

// --- Small helpers --------------------------------------------------------------

let toastTimer;
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

function setStatus(el, text, kind = "") {
  el.hidden = !text;
  el.textContent = text || "";
  el.className = `status ${kind}`.trim();
}

const fmt = (v) => (v === null || v === undefined ? "–" : String(Math.round(v * 100) / 100));
const isBracket = () => ui.draft && ui.draft.part_type === "l_bracket";
const parseNumber = (text) => (text.trim() === "" || Number.isNaN(Number(text)) ? null : Number(text));

// --- Top bar and upload card ------------------------------------------------------

function renderServerState() {
  const s = ui.server;
  const badge = $("#ai-badge");
  if (s.ai.available) {
    badge.textContent = `AI reading on · ${s.ai.model}`;
    badge.className = "badge ok";
    badge.title = "Images are read by the AI.";
  } else {
    badge.textContent = "Offline demo mode";
    badge.className = "badge offline";
    badge.title = "No AI key is configured. The bundled test files are read from the answer key; other files must be filled in by hand.";
  }
  const chip = $("#version-chip");
  chip.hidden = !s.current;
  if (s.current) chip.textContent = `${s.current.part.name || "Part"} · version ${s.history.length}`;
  $("#undo-btn").disabled = !s.can_undo;

  const list = $("#sample-list");
  list.replaceChildren();
  for (const sample of s.samples) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `sample ${sample.mode}`;
    button.append(sample.label + " ");
    const small = document.createElement("small");
    small.textContent = sample.detail;
    button.append(small);
    button.addEventListener("click", () => loadSample(sample));
    list.append(button);
  }
  $("#samples").hidden = s.samples.length === 0;
  renderUploadCard();
  renderOutputs();
}

function renderUploadCard() {
  $$(".segmented button").forEach((b) => b.classList.toggle("active", b.dataset.mode === ui.mode));
  const needsPart = ui.mode === "markup" && !(ui.server && ui.server.current);
  $("#mode-hint").textContent = needsPart
    ? "Markups change an existing part. Create the part from its drawing first."
    : MODE_HINTS[ui.mode];
  $("#request-input").placeholder = ui.mode === "markup" ? "Apply the markups" : "Create this part";
  $("#read-btn").disabled = !ui.file || needsPart;
  const zone = $("#dropzone");
  zone.classList.toggle("has-file", !!ui.file);
  if (ui.file) {
    $("#drop-text").replaceChildren(Object.assign(document.createElement("b"), { textContent: ui.file.name }),
      document.createElement("br"), Object.assign(document.createElement("small"), { textContent: "Click or drop to choose another file" }));
  } else {
    $("#drop-text").innerHTML = "<b>Drop a file here</b> or click to choose<br><small>PDF, PNG, JPEG or phone photo</small>";
  }
}

function setMode(mode) {
  ui.mode = mode;
  renderUploadCard();
}

function setFile(file) {
  ui.file = file;
  setStatus($("#read-status"), "");
  renderUploadCard();
}

async function loadSample(sample) {
  try {
    const response = await fetch(`/api/samples/${sample.file}`);
    if (!response.ok) throw new Error("The test file could not be loaded.");
    const blob = await response.blob();
    setMode(sample.mode);
    $("#request-input").value = sample.request;
    setFile(new File([blob], sample.file.split("/").pop(), { type: blob.type }));
  } catch (err) {
    setStatus($("#read-status"), err.message, "error");
  }
}

async function readFile() {
  if (!ui.file) return;
  const status = $("#read-status");
  const button = $("#read-btn");
  button.disabled = true;
  setStatus(status, ui.server.ai.available ? "The AI is reading the image…" : "Reading…", "busy");
  const form = new FormData();
  form.append("file", ui.file);
  form.append("request", $("#request-input").value);
  form.append("mode", ui.mode);
  try {
    const result = await api("/api/read", { method: "POST", body: form });
    ui.draft = result.draft;
    ui.uncertain = new Set(result.uncertain);
    ui.changed = new Set(result.changed);
    ui.filled = result.filled || {};
    ui.issues = [];
    ui.how = `${result.mode === "markup" ? "Markups from" : "Read from"} ${ui.file.name}`;
    renderConfirm(result);
    $("#source-img").src = `/api/preview?t=${Date.now()}`;
    $("#source-img").hidden = false;
    $("#source-empty").hidden = true;
    showTab("source");
    setStatus(status, "");
    scheduleCheck();
    $("#confirm-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    setStatus(status, err.message, "error");
  } finally {
    renderUploadCard();
  }
}

// --- Confirmation form --------------------------------------------------------------

function renderConfirm(result = null) {
  const card = $("#confirm-card");
  card.hidden = !ui.draft;
  if (!ui.draft) return;

  if (result) {
    const notes = $("#notes");
    notes.hidden = !result.notes;
    notes.textContent = result.notes || "";
    notes.classList.toggle("offline", result.source !== "ai");

    const changes = $("#changes");
    const list = $("#change-list");
    list.replaceChildren();
    for (const change of result.changes) {
      const li = document.createElement("li");
      li.append(Object.assign(document.createElement("b"), { textContent: change.label }));
      if (change.uncertain) li.append(Object.assign(document.createElement("span"), { className: "tag", textContent: "check" }));
      if (change.markup_text) li.append(Object.assign(document.createElement("q"), { textContent: change.markup_text }));
      list.append(li);
    }
    for (const problem of result.problems) {
      list.append(Object.assign(document.createElement("li"), { className: "problem", textContent: problem }));
    }
    if (result.mode === "markup" && list.children.length === 0) {
      list.append(Object.assign(document.createElement("li"), { className: "muted", textContent: "No changes were found in this image." }));
    }
    changes.hidden = result.mode !== "markup";

    const flagged = ui.uncertain.size;
    $("#confirm-hint").textContent = result.mode === "markup"
      ? "These are the current values with the markups applied. Correct anything that is wrong, then apply."
      : flagged
        ? `${flagged} value${flagged === 1 ? " is" : "s are"} highlighted for checking. Compare with the sheet on the right, correct anything that is wrong, then apply.`
        : "Compare with the sheet on the right, correct anything that is wrong, then apply.";
  }
  renderFormValues();
}

function clearReadResult(hint) {
  ui.uncertain = new Set();
  ui.changed = new Set();
  ui.filled = {};
  ui.issues = [];
  ui.how = "Edited by hand";
  $("#notes").hidden = true;
  $("#changes").hidden = true;
  $("#confirm-hint").textContent = hint;
}

function renderFormValues() {
  const d = ui.draft;
  const form = $("#part-form");
  const bracket = isBracket();

  // Materials: the rules table, plus whatever was read if it is not in the table.
  const materialSelect = form.elements.material;
  const names = ui.server.rules.materials.map((m) => m.name);
  materialSelect.replaceChildren();
  for (const name of names) materialSelect.append(new Option(name, name));
  if (d.material && !names.includes(d.material)) materialSelect.append(new Option(`${d.material} (not in rules table)`, d.material));
  materialSelect.value = d.material || "";

  form.elements.part_type.value = d.part_type;
  form.elements.name.value = d.name || "";
  for (const field of NUMBER_FIELDS) form.elements[field].value = d[field] ?? "";
  renderThicknessOptions();

  $("#flange-a-label").innerHTML = bracket ? "Flange A <i>mm, outside</i>" : "Length <i>mm</i>";
  $("#width-label").innerHTML = bracket ? "Width <i>mm, along the bend</i>" : "Width <i>mm</i>";
  $("#from-edge-head").textContent = bracket ? "From free edge" : "From bottom";
  $$(".bracket-only").forEach((el) => { el.hidden = !bracket; });

  const body = $("#holes-table tbody");
  body.replaceChildren();
  d.holes.forEach((hole, i) => {
    const row = document.createElement("tr");
    row.append(Object.assign(document.createElement("td"), { textContent: String(i + 1) }));
    if (bracket) {
      const cell = document.createElement("td");
      cell.dataset.path = `holes.${i}.flange`;
      const select = document.createElement("select");
      select.append(new Option("A", "A"), new Option("B", "B"));
      select.value = hole.flange || "A";
      select.setAttribute("aria-label", `Hole ${i + 1} flange`);
      select.addEventListener("change", () => { hole.flange = select.value; touched(cell.dataset.path); });
      cell.append(select);
      row.append(cell);
    }
    for (const field of HOLE_FIELDS) {
      const cell = document.createElement("td");
      cell.dataset.path = `holes.${i}.${field}`;
      const input = Object.assign(document.createElement("input"), { type: "number", step: "any", min: "0" });
      input.value = hole[field] ?? "";
      input.setAttribute("aria-label", `Hole ${i + 1} ${field.replace("_", " ")}`);
      input.addEventListener("input", () => { hole[field] = parseNumber(input.value); touched(cell.dataset.path); });
      cell.append(input);
      row.append(cell);
    }
    const last = document.createElement("td");
    const remove = Object.assign(document.createElement("button"), { type: "button", className: "icon-btn", textContent: "×", title: `Remove hole ${i + 1}` });
    remove.addEventListener("click", () => removeHole(i));
    last.append(remove);
    row.append(last);
    body.append(row);
  });
  $("#holes-table").hidden = d.holes.length === 0;
  $("#no-holes").hidden = d.holes.length !== 0;
  renderMarks();
}

function renderThicknessOptions() {
  const list = $("#thickness-options");
  list.replaceChildren();
  const material = ui.server.rules.materials.find((m) => m.name === ui.draft.material);
  for (const t of material ? material.thicknesses : []) list.append(new Option(String(t), String(t)));
}

// Highlights: uncertain (amber), changed by markup (violet), failing a check (red).
function renderMarks() {
  const invalid = new Set(ui.issues.filter((i) => i.field).map((i) => i.field));
  for (const el of $$("#part-form [data-path]")) {
    const path = el.dataset.path;
    el.classList.toggle("uncertain", ui.uncertain.has(path));
    el.classList.toggle("changed", ui.changed.has(path));
    el.classList.toggle("invalid", invalid.has(path));
    if (el.classList.contains("field")) {
      let why = $("small.why", el);
      const text = ui.filled[path];
      if (text && !why) { why = Object.assign(document.createElement("small"), { className: "why" }); el.append(why); }
      if (why) { why.textContent = text || ""; why.hidden = !text; }
    }
  }
}

function renderIssues({ built = false } = {}) {
  const list = $("#issues");
  list.replaceChildren();
  for (const issue of ui.issues) {
    const li = Object.assign(document.createElement("li"), { className: issue.severity, textContent: issue.message });
    if (issue.field) {
      li.dataset.field = issue.field;
      li.title = "Click to go to this value";
      li.addEventListener("click", () => $(`#part-form [data-path="${issue.field}"] :is(input, select)`)?.focus());
    }
    list.append(li);
  }
  if (built && ui.issues.length === 0) {
    list.append(Object.assign(document.createElement("li"), { className: "ok", textContent: "All engineering rules passed." }));
  }
  list.hidden = list.children.length === 0;
  const onlyRules = ui.issues.length > 0 && ui.issues.every((i) => i.severity === "rule");
  $("#force-btn").hidden = !onlyRules || built;
  renderMarks();
}

function touched(path) {
  // Once the engineer has edited a value it no longer needs the "check" highlight.
  ui.uncertain.delete(path);
  delete ui.filled[path];
  renderMarks();
  scheduleCheck();
}

function removeHole(index) {
  ui.draft.holes.splice(index, 1);
  const shift = (set) => new Set([...set].flatMap((path) => {
    const m = path.match(/^holes\.(\d+)\.(.+)$/);
    if (!m) return [path];
    const n = Number(m[1]);
    if (n === index) return [];
    return [`holes.${n > index ? n - 1 : n}.${m[2]}`];
  }));
  ui.uncertain = shift(ui.uncertain);
  ui.changed = shift(ui.changed);
  renderFormValues();
  scheduleCheck();
}

let checkTimer;
function scheduleCheck() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    if (!ui.draft) return;
    try {
      const result = await postJson("/api/check", { part: ui.draft });
      ui.issues = result.issues;
      renderIssues();
    } catch { /* the check runs again on Apply */ }
  }, 350);
}

async function applyPart(buildAnyway = false) {
  if (!ui.draft) return;
  clearTimeout(checkTimer);
  const status = $("#apply-status");
  const buttons = [$("#apply-btn"), $("#force-btn")];
  buttons.forEach((b) => { b.disabled = true; });
  setStatus(status, "Checking the rules and building the part…", "busy");
  try {
    const result = await postJson("/api/apply", { part: ui.draft, how: ui.how, build_anyway: buildAnyway });
    ui.issues = result.issues || [];
    if (!result.built) {
      renderIssues();
      setStatus(status, "Not built. Fix the problems above.", "error");
      $("#issues").scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }
    ui.server = result;
    ui.draft = structuredClone(result.current.part);
    clearReadResult("This is the current part. Change any value and apply to rebuild it.");
    ui.issues = result.issues || [];
    renderServerState();
    renderFormValues();
    renderIssues({ built: true });
    setStatus(status, "");
    showTab("model");
    toast(`Built ${result.current.part.name || "part"} · version ${result.history.length}`);
  } catch (err) {
    setStatus(status, err.message, "error");
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}

function adoptCurrentPart(hint) {
  const current = ui.server.current;
  ui.draft = current ? structuredClone(current.part) : null;
  clearReadResult(hint);
  renderConfirm();
  renderIssues();
}

// --- Outputs ---------------------------------------------------------------------------

function showTab(name) {
  $$(".tabs button[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".pane").forEach((p) => { p.hidden = p.dataset.pane !== name; });
  if (name === "model") viewer.resize();
}

async function renderOutputs() {
  const current = ui.server.current;
  const has = !!current;
  $("#downloads").hidden = !has;
  for (const pane of ["flat", "sheet", "data"]) $(`.pane[data-pane="${pane}"] .empty`).hidden = has;
  $("#model-empty").hidden = has;
  $("#viewer").hidden = !has;
  $("#viewer-hint").hidden = !has;
  $("#flat-holder").hidden = !has;
  $("#sheet-link").hidden = !has;
  $("#data-pre").hidden = !has;

  const facts = $("#facts");
  facts.replaceChildren();
  const history = $("#history");
  history.replaceChildren();
  if (!has) { ui.shownVersion = null; viewer.clear(); $("#sheet-img").removeAttribute("src"); return; }

  const add = (label, value) => {
    const span = document.createElement("span");
    span.append(`${label} `, Object.assign(document.createElement("b"), { textContent: value }));
    facts.append(span);
  };
  const d = current.derived;
  add("Flat length", `${fmt(d.flat_length_mm)} mm`);
  add("Flat size", `${fmt(d.flat_size_mm[0])} × ${fmt(d.flat_size_mm[1])} mm`);
  if (d.k_factor !== undefined) add("K-factor", String(d.k_factor));

  ui.server.history.forEach((v, i) => {
    const li = Object.assign(document.createElement("li"), { textContent: `v${i + 1} · ${v.how}`, title: v.how });
    if (v.number === current.number) li.className = "current";
    history.append(li);
  });

  if (ui.shownVersion === current.number) return;
  ui.shownVersion = current.number;
  for (const link of $$("#downloads a[data-kind]")) link.href = `${current.downloads[link.dataset.kind]}?download=true`;
  $("#data-pre").textContent = JSON.stringify(current.part_json, null, 2);
  $("#sheet-img").src = current.sheet_png_url;
  $("#sheet-link").href = current.downloads.pdf;
  $("#zip-link").href = current.zip_url;
  try {
    const [mesh, svg] = await Promise.all([
      fetch(current.mesh_url).then((r) => r.json()),
      fetch(current.flat_svg_url).then((r) => r.text()),
    ]);
    if (ui.shownVersion !== current.number) return;  // a newer version arrived meanwhile
    $("#flat-holder").innerHTML = svg;
    viewer.show(mesh);
  } catch {
    toast("The 3D view could not be loaded.");
  }
}

// --- 3D viewer ----------------------------------------------------------------------------

const viewer = (() => {
  const canvas = $("#viewer");
  let renderer, scene, camera, controls, group, lastBox;

  function init() {
    if (renderer) return;
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(32, 1, 0.1, 10000);
    camera.up.set(0, 0, 1);  // CAD convention: z is up
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a94a3, 1.5));
    const key = new THREE.DirectionalLight(0xffffff, 1.9);
    key.position.set(1.2, -1.6, 2.4);
    const fill = new THREE.DirectionalLight(0xffffff, 0.7);
    fill.position.set(-2, 1.5, 0.6);
    scene.add(key, fill);
    controls = new OrbitControls(camera, canvas);
    controls.addEventListener("change", render);
    new ResizeObserver(resize).observe(canvas.parentElement);
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => lastMesh && show(lastMesh));
  }

  function render() { if (renderer) renderer.render(scene, camera); }

  function resize() {
    if (!renderer) return;
    const { clientWidth: w, clientHeight: h } = canvas.parentElement;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    render();
  }

  let lastMesh = null;
  function show(mesh) {
    init();
    lastMesh = mesh;
    const keepView = group && lastBox && sameBox(lastBox, mesh.bbox);
    clearGroup();
    group = new THREE.Group();
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
    geometry.setIndex(mesh.indices);
    geometry.computeVertexNormals();
    group.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: dark ? 0xaab4c2 : 0xc3ccd8, metalness: 0.45, roughness: 0.5, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
    })));

    const segments = [];
    for (const line of mesh.edges) {
      for (let i = 0; i + 5 < line.length; i += 3) segments.push(...line.slice(i, i + 6));
    }
    const edgeGeometry = new THREE.BufferGeometry();
    edgeGeometry.setAttribute("position", new THREE.Float32BufferAttribute(segments, 3));
    group.add(new THREE.LineSegments(edgeGeometry, new THREE.LineBasicMaterial({ color: dark ? 0x0b0f14 : 0x1f2937 })));
    scene.add(group);

    if (!keepView) frame(mesh.bbox);
    lastBox = mesh.bbox;
    resize();
  }

  const sameBox = (a, b) => [...a.min, ...a.max].every((v, i) => Math.abs(v - [...b.min, ...b.max][i]) < 1e-6);

  function frame(bbox) {
    const min = new THREE.Vector3(...bbox.min), max = new THREE.Vector3(...bbox.max);
    const centre = min.clone().add(max).multiplyScalar(0.5);
    const radius = max.clone().sub(min).length() / 2;
    const distance = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.08;
    camera.position.copy(centre).add(new THREE.Vector3(-0.85, -1.25, 0.95).normalize().multiplyScalar(distance));
    camera.near = distance / 100;
    camera.far = distance * 100;
    camera.updateProjectionMatrix();
    controls.target.copy(centre);
    controls.update();
  }

  function clearGroup() {
    if (!group) return;
    scene.remove(group);
    group.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
    group = null;
  }

  function clear() { clearGroup(); lastBox = null; lastMesh = null; render(); }

  return { show, resize, clear };
})();

// --- Events -------------------------------------------------------------------------------------

$$(".segmented button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
$$(".tabs button[data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

$("#file-input").addEventListener("change", (e) => { if (e.target.files[0]) setFile(e.target.files[0]); e.target.value = ""; });
const zone = $("#dropzone");
["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add("over"); }));
["dragleave", "drop"].forEach((type) => zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
zone.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });

$("#request-input").addEventListener("input", (e) => {
  // "Apply the markups" switches to markup mode, "Create this part" back again.
  const text = e.target.value;
  if (MARKUP_WORDS.test(text)) setMode("markup");
  else if (/creat|build|make|new/i.test(text)) setMode("create");
});
$("#request-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !$("#read-btn").disabled) readFile(); });
$("#read-btn").addEventListener("click", readFile);

const form = $("#part-form");
form.addEventListener("submit", (e) => { e.preventDefault(); applyPart(false); });
$("#force-btn").addEventListener("click", () => applyPart(true));
form.elements.name.addEventListener("input", (e) => { ui.draft.name = e.target.value; touched("name"); });
form.elements.material.addEventListener("change", (e) => { ui.draft.material = e.target.value; renderThicknessOptions(); touched("material"); });
form.elements.part_type.addEventListener("change", (e) => {
  ui.draft.part_type = e.target.value;
  if (e.target.value === "plate") { ui.draft.flange_b = null; ui.draft.bend_radius = null; ui.draft.holes.forEach((h) => { h.flange = "A"; }); }
  ui.uncertain.delete("part_type");
  renderFormValues();
  scheduleCheck();
});
for (const field of NUMBER_FIELDS) {
  form.elements[field].addEventListener("input", (e) => { ui.draft[field] = parseNumber(e.target.value); touched(field); });
}
$("#add-hole").addEventListener("click", () => {
  ui.draft.holes.push({ flange: "A", from_edge: null, from_left: null, diameter: null });
  renderFormValues();
  $("#holes-table tbody tr:last-child input")?.focus();
});

$("#undo-btn").addEventListener("click", async () => {
  try {
    ui.server = await api("/api/undo", { method: "POST" });
    renderServerState();
    adoptCurrentPart("Stepped back to the previous version. Change any value and apply to rebuild it.");
    toast(`Back to version ${ui.server.history.length}`);
  } catch (err) { toast(err.message); }
});

$("#reset-btn").addEventListener("click", async () => {
  try {
    ui.server = await api("/api/reset", { method: "POST" });
    ui.file = null;
    $("#request-input").value = "";
    $("#source-img").hidden = true;
    $("#source-empty").hidden = false;
    setMode("create");
    renderServerState();
    adoptCurrentPart("");
    showTab("model");
  } catch (err) { toast(err.message); }
});

// --- Start -----------------------------------------------------------------------------------------

try {
  ui.server = await api("/api/state");
  renderServerState();
  if (ui.server.current) adoptCurrentPart("This is the current part. Change any value and apply to rebuild it.");
} catch (err) {
  setStatus($("#read-status"), err.message, "error");
}
