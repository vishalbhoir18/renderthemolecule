"use strict";

const SELECTS = ["style", "color", "material", "viewpoint", "resolution", "quality", "background"];
const CHECKS = ["ligands", "assembly", "credit"];
const STORAGE_KEY = "rtm-options";
const VISITOR = ["name", "email", "institution", "country"];
const VISITOR_KEY = "rtm-visitor";  // the visitor's details, kept only in this browser for next time
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PDB_RE = /^(?:[1-9][a-z0-9]{3}|pdb_[0-9a-z]{8})$/i;
const PREVIEW_FIELDS = ["style", "color", "background", "resolution", "ligands", "assembly"];
const POLL_MS = 1500;

const $ = (id) => document.getElementById(id);
const form = $("render-form");
const pdbInput = $("pdb_id");
const submitBtn = $("submit");

let pollTimer = null;
let tickTimer = null;
let currentJob = null;       // id of the job this page is following
let currentJobState = null;  // its latest status from the server
let previewTimer = null;
let linkCamera = null;       // { pdb_id, camera } from a shared link, until the preview shows it

function readStored(key = STORAGE_KEY) {
  try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; }
}
function writeStored(values, key = STORAGE_KEY) {
  try { localStorage.setItem(key, JSON.stringify(values)); } catch { /* storage unavailable */ }
}

async function loadOptions() {
  const resp = await fetch("/api/options");
  const data = await resp.json();
  const { choices, defaults } = data;
  Preview.setColors(data);  // so the preview's colours are Blender's
  const params = new URLSearchParams(location.search);
  const stored = readStored();
  const visitor = readStored(VISITOR_KEY);
  for (const field of VISITOR) $(field).value = visitor[field] || "";
  loadCountries();

  for (const name of SELECTS) {
    const select = $(name);
    for (const { value, label } of choices[name]) {
      select.add(new Option(label, value));
    }
    const wanted = params.get(name) ?? stored[name] ?? defaults[name];
    if (choices[name].some((c) => c.value === wanted)) select.value = wanted;
  }
  for (const name of CHECKS) {
    const fromUrl = params.get(name);
    $(name).checked = fromUrl !== null ? fromUrl === "1" || fromUrl === "true"
      : stored[name] ?? defaults[name];
  }

  const id = params.get("id");
  if (id) {
    pdbInput.value = id.toUpperCase();
    const camera = parseCamera(params.get("cam"));
    if (camera) {
      linkCamera = { pdb_id: id.toLowerCase(), camera };
      Preview.useCamera(camera);
      $("use_view").disabled = false;
      setUseView(true);
    }
    updatePreview({ immediate: true });
    const missing = VISITOR.find((field) => !$(field).value.trim());
    if (!missing) {
      form.requestSubmit();
    } else {
      showError("Enter your name, email, institution and country, then press Render image.");
      $(missing).focus();
    }
  }
}

// Country suggestions; typing any other country still works.
async function loadCountries() {
  try {
    const names = await (await fetch("/static/countries.json")).json();
    $("countries").replaceChildren(...names.map((name) => new Option(name)));
  } catch { /* suggestions are optional */ }
}

function formValues() {
  const values = { pdb_id: pdbInput.value.trim() };
  for (const field of VISITOR) values[field] = $(field).value.trim();
  for (const name of SELECTS) values[name] = $(name).value;
  for (const name of CHECKS) values[name] = $(name).checked;
  if ($("use_view").checked) {
    const code = values.pdb_id.toLowerCase();
    const camera = Preview.shownId === code ? Preview.camera() : null;
    values.camera = camera || (linkCamera?.pdb_id === code ? linkCamera.camera : null);
  }
  return values;
}

// Camera in links: px,py,pz,tx,ty,tz,ux,uy,uz,fov (as RenderRequest.share_query writes it).
function cameraParam(camera) {
  return [...camera.position, ...camera.target, ...camera.up, camera.fov].join(",");
}

function parseCamera(text) {
  const v = (text || "").split(",").map(Number);
  if (v.length !== 10 || !v.every(Number.isFinite)) return null;
  return { position: v.slice(0, 3), target: v.slice(3, 6), up: v.slice(6, 9), fov: v[9] };
}

// First problem with the form, as [message, field to focus], or null.
function formProblem(values) {
  if (!values.name) return ["Please enter your name.", $("name")];
  if (!EMAIL_RE.test(values.email)) {
    return ["Please enter a valid email address, like name@university.edu.", $("email")];
  }
  if (!values.institution) return ["Please enter your institution.", $("institution")];
  if (!values.country) return ["Please enter your country.", $("country")];
  if (!values.pdb_id) return ["Please enter a PDB ID, for example 4HHB.", pdbInput];
  return null;
}

function updateUrl(values) {
  const params = new URLSearchParams({ id: values.pdb_id.toUpperCase() });
  for (const name of SELECTS) params.set(name, values[name]);
  for (const name of CHECKS) params.set(name, values[name] ? "1" : "0");
  if (values.camera) params.set("cam", cameraParam(values.camera));
  history.replaceState(null, "", `?${params}`);
}

// --- Result tabs: the 3D preview and the rendered image -------------------------------------

function selectTab(name) {
  for (const tab of ["preview", "image"]) {
    const selected = tab === name;
    $(`tab-${tab}`).setAttribute("aria-selected", String(selected));
    $(`tab-${tab}`).tabIndex = selected ? 0 : -1;
    $(`${tab}-pane`).hidden = !selected;
  }
  if (name === "preview") Preview.resize();
}

for (const tab of ["preview", "image"]) {
  $(`tab-${tab}`).addEventListener("click", () => selectTab(tab));
  $(`tab-${tab}`).addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const other = tab === "preview" ? "image" : "preview";
    selectTab(other);
    $(`tab-${other}`).focus();
  });
}

// --- 3D preview --------------------------------------------------------------------------

function previewOptions() {
  const options = { pdb_id: pdbInput.value.trim().toLowerCase(), viewpoint: $("viewpoint").value };
  for (const name of PREVIEW_FIELDS) options[name] = CHECKS.includes(name) ? $(name).checked : $(name).value;
  return options;
}

function showViewerMessage(text, isError = false) {
  const message = $("viewer-message");
  message.textContent = text;
  message.hidden = !text;
  message.classList.toggle("is-error", isError);
}

// "Render this view": send the preview's camera instead of a preset viewpoint.
function setUseView(on) {
  $("use_view").checked = on;
  $("viewpoint").disabled = on;
  $("viewpoint-note").hidden = !on;
  if (!submitBtn.disabled) submitBtn.textContent = idleLabel();
}

function idleLabel() {
  return $("use_view").checked ? "Render this view" : "Render image";
}

function updatePreview({ immediate = false } = {}) {
  clearTimeout(previewTimer);
  const code = pdbInput.value.trim().toLowerCase();
  if (!PDB_RE.test(code)) return;  // keep showing the last molecule while typing
  if (!Preview.supported()) {
    showViewerMessage("This browser cannot show 3D graphics (WebGL), so there is no preview. Rendering still works.");
    return;
  }
  if (Preview.shownId && Preview.shownId !== code && linkCamera?.pdb_id !== code) {
    setUseView(false);  // a view chosen for another molecule does not apply
    Preview.forgetView();
  }
  previewTimer = setTimeout(async () => {
    selectTab("preview");  // also keeps the viewer visible (and sized) while it changes
    await Preview.show($("viewer"), previewOptions());
    const ready = Preview.shownId !== null;
    $("use_view").disabled = !ready && !linkCamera;
    $("reset-view").disabled = !ready;
    $("save-preview").disabled = !ready;
    if (Preview.shownId === linkCamera?.pdb_id) linkCamera = null;
  }, immediate ? 0 : 500);
}

Preview.on("status", (text, isError) => showViewerMessage(text, isError));
Preview.on("note", (text) => {
  $("viewer-note").textContent = text;
  $("viewer-note").hidden = !text;
});
Preview.on("move", () => {
  $("use_view").disabled = false;
  setUseView(true);
});

pdbInput.addEventListener("input", () => updatePreview());
for (const name of PREVIEW_FIELDS) $(name).addEventListener("change", () => updatePreview({ immediate: true }));

$("viewpoint").addEventListener("change", () => Preview.frame($("viewpoint").value));

$("use_view").addEventListener("change", () => {
  setUseView($("use_view").checked);
  if (!$("use_view").checked) Preview.frame($("viewpoint").value);
});

$("reset-view").addEventListener("click", () => {
  setUseView(false);
  Preview.frame($("viewpoint").value);
});

// "Save preview image": the Mol* view as a PNG, straight from the browser (no server, no render).
$("save-preview").addEventListener("click", async () => {
  const button = $("save-preview");
  const code = Preview.shownId;
  if (!code) return;
  const [width, height] = $("resolution").value.split("x").map(Number);
  const background = $("background").value;
  button.disabled = true;
  button.textContent = "Saving…";
  try {
    const picture = await loadImage(await Preview.image(width, height, background === "transparent"));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(picture, 0, 0, width, height);
    if ($("credit").checked) drawCredit(ctx, width, height, previewCredit(code), background);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${code}_${$("style").value}_${$("color").value}_preview.png`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  } catch (err) {
    showViewerMessage(`The preview image could not be saved: ${err.message || err}`, true);
  } finally {
    button.disabled = false;
    button.textContent = "Save preview image";
  }
});

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("the image could not be read"));
    image.src = src;
  });
}

// Like the credit line on rendered images (app/about.py credit_line), naming Mol*.
function previewCredit(code) {
  return `PDB ${code.replace(/^pdb_0*/, "").toUpperCase()} · Mol* · Render the Molecule by Vishal Bhoir`;
}

// Small grey text in the bottom-right corner, scaled to the image (as _draw_credit in
// app/blender_render.py).
function drawCredit(ctx, width, height, text, background) {
  const margin = Math.max(8, Math.round(width / 100));
  let size = Math.max(11, Math.round(width / 90));
  const font = (px) => `${px}px system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif`;
  ctx.font = font(size);
  while (ctx.measureText(text).width > width - 2 * margin && size > 8) {
    size -= 1;
    ctx.font = font(size);
  }
  ctx.fillStyle = { white: "rgb(110,110,110)", black: "rgb(165,165,165)" }[background] || "rgb(128,128,128)";
  ctx.textAlign = "right";
  ctx.textBaseline = "bottom";
  ctx.fillText(text, width - margin, height - margin);
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

function setStatus(text) {
  $("status-text").textContent = text;
  $("status").hidden = !text;
}

function stopPolling() {
  clearTimeout(pollTimer);
  clearInterval(tickTimer);
  pollTimer = tickTimer = null;
}

function setBusy(busy) {
  submitBtn.disabled = busy;
  submitBtn.textContent = busy ? "Rendering…" : idleLabel();
}

function describe(job, startedAt) {
  const id = job.pdb_id.toUpperCase();
  if (job.status === "queued") {
    const n = job.jobs_ahead ?? 0;
    return n > 0 ? `Waiting in the queue: ${n} render${n === 1 ? "" : "s"} ahead of yours…`
      : "Starting…";
  }
  const secs = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
  if (job.stage === "downloading") return `Downloading ${id} from the Protein Data Bank…`;
  return `Rendering ${id} with Blender… ${secs} s`;
}

function showResult(job, values) {
  const img = $("image");
  const figure = $("figure");
  img.onload = () => {
    $("placeholder").hidden = true;
    img.hidden = false;
    figure.classList.add("has-image");
    figure.classList.toggle("transparent", values.background === "transparent");
  };
  img.onerror = () => showError("The image could not be loaded. Please try rendering again.");
  img.alt = `${job.pdb_id.toUpperCase()} rendered in ${$("style").selectedOptions[0].text} style`;
  img.src = job.image_url;

  const download = $("download");
  download.href = job.image_url;
  download.download = job.download_name;
  const code = job.pdb_id.replace(/^pdb_0*/, "").toUpperCase();
  $("rcsb").href = `https://www.rcsb.org/structure/${encodeURIComponent(code)}`;
  $("meta").textContent = job.cached ? "Served from cache" : `Rendered in ${job.render_s} s`;
  $("actions").hidden = false;
  showCitation(job.pdb_id);
}

async function showCitation(pdbId) {
  try {
    const resp = await fetch(`/api/cite?pdb_id=${encodeURIComponent(pdbId)}`);
    if (!resp.ok) return;
    const cite = await resp.json();
    $("cite-legend").textContent = cite.legend;
    const list = $("cite-refs");
    list.replaceChildren(...cite.references.map((text) => {
      const li = document.createElement("li");
      li.textContent = text;
      return li;
    }));
    $("cite").hidden = false;
  } catch { /* the image is still usable without the citation box */ }
}

$("copy-cite").addEventListener("click", async () => {
  const refs = [...$("cite-refs").children].map((li, i) => `${i + 1}. ${li.textContent}`);
  const text = `${$("cite-legend").textContent}\n\nReferences:\n${refs.join("\n")}`;
  const button = $("copy-cite");
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied";
  } catch {
    button.textContent = "Select and copy";
  }
  setTimeout(() => { button.textContent = "Copy"; }, 2000);
});

async function poll(jobId, values, startedAt) {
  let job;
  try {
    const resp = await fetch(`/api/jobs/${jobId}`);
    job = await resp.json();
    if (!resp.ok) throw new Error(job.error || `Server error ${resp.status}`);
  } catch (err) {
    stopPolling(); setBusy(false); setStatus("");
    showError(err.message || "Lost contact with the server.");
    return;
  }
  if (jobId !== currentJob) return;

  if (job.status === "running" && !startedAt.running) startedAt.running = Date.now();
  currentJobState = job;

  if (job.status === "done") {
    stopPolling(); setBusy(false); setStatus("");
    showResult(job, values);
    selectTab("image");
  } else if (job.status === "failed") {
    stopPolling(); setBusy(false); setStatus("");
    showError(job.error || "Rendering failed.");
  } else {
    setStatus(describe(job, startedAt.running || Date.now()));
    pollTimer = setTimeout(() => poll(jobId, values, startedAt), POLL_MS);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = formValues();
  showError("");
  const problem = formProblem(values);
  if (problem) {
    showError(problem[0]);
    problem[1].focus();
    return;
  }
  stopPolling();
  setBusy(true);
  setStatus("Sending request…");
  $("actions").hidden = true;
  $("cite").hidden = true;
  const options = {};
  for (const name of [...SELECTS, ...CHECKS]) options[name] = values[name];
  writeStored(options);
  writeStored(Object.fromEntries(VISITOR.map((field) => [field, values[field]])), VISITOR_KEY);
  updateUrl(values);  // shareable link: options and view only, never name or email

  let job;
  try {
    const resp = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    job = await resp.json();
    if (!resp.ok) throw new Error(job.error || `Server error ${resp.status}`);
  } catch (err) {
    setBusy(false); setStatus("");
    showError(err.message || "Could not reach the server.");
    return;
  }

  currentJob = job.id;
  const startedAt = { running: job.status === "running" ? Date.now() : null };
  tickTimer = setInterval(() => {
    if (currentJobState && currentJobState.id === job.id && currentJobState.status === "running") {
      setStatus(describe(currentJobState, startedAt.running || Date.now()));
    }
  }, 1000);
  currentJobState = job;
  poll(job.id, values, startedAt);
});

for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    pdbInput.value = chip.dataset.id;
    pdbInput.focus();
    updatePreview({ immediate: true });
  });
}

loadOptions().catch(() => showError("Could not load options from the server. Please reload the page."));
