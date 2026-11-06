"use strict";

const SELECTS = ["style", "color", "material", "viewpoint", "resolution", "quality", "background"];
const CHECKS = ["ligands", "assembly", "credit"];
const STORAGE_KEY = "rtm-options";
const VISITOR = ["name", "email", "institution", "country"];
const VISITOR_KEY = "rtm-visitor";  // the visitor's details, kept only in this browser for next time
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const POLL_MS = 1500;

const $ = (id) => document.getElementById(id);
const form = $("render-form");
const pdbInput = $("pdb_id");
const submitBtn = $("submit");

let pollTimer = null;
let tickTimer = null;
let currentJob = null;       // id of the job this page is following
let currentJobState = null;  // its latest status from the server

function readStored(key = STORAGE_KEY) {
  try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; }
}
function writeStored(values, key = STORAGE_KEY) {
  try { localStorage.setItem(key, JSON.stringify(values)); } catch { /* storage unavailable */ }
}

async function loadOptions() {
  const resp = await fetch("/api/options");
  const { choices, defaults } = await resp.json();
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
  return values;
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
  history.replaceState(null, "", `?${params}`);
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
  submitBtn.textContent = busy ? "Rendering…" : "Render image";
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
  updateUrl(values);  // shareable link: options only, never name or email

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
  });
}

loadOptions().catch(() => showError("Could not load options from the server. Please reload the page."));
