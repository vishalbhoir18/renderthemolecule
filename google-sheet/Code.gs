/**
 * Render the Molecule → Google Sheet recorder.
 *
 * Paste this into Extensions → Apps Script of a Google Sheet, set TOKEN and
 * COLAB_TOKEN, and deploy it as a web app (step-by-step in the README, section
 * "Record who rendered what in a Google Sheet").
 * Each finished render is appended as one row to the "Renders" tab.
 */

// Private password of the website. Put the same value in the SHEET_TOKEN secret on GitHub.
const TOKEN = "CHANGE-ME";

// Public key used by the Google Colab notebook (notebooks/colab_recording.json).
// Anyone who reads the notebook can see it, so rows sent with it are always
// marked "Colab", and each request may add at most COLAB_MAX_ROWS rows.
// If it is ever abused, change it here and in colab_recording.json.
const COLAB_TOKEN = "CHANGE-ME-COLAB";
const COLAB_MAX_ROWS = 3;

const SHEET_NAME = "Renders";

// Column order; must match ROW_KEYS in app/sheet.py.
const KEYS = [
  "time", "name", "email", "pdb_id", "style", "color", "material", "viewpoint",
  "resolution", "quality", "background", "ligands", "assembly", "credit",
  "status", "cached", "render_s", "error", "link",
  "source", "institution", "country",
];
const HEADERS = [
  "Time", "Name", "Email", "PDB ID", "Style", "Colour", "Material", "View",
  "Size", "Quality", "Background", "Ligands", "Assembly", "Credit line",
  "Status", "From cache", "Render time (s)", "Error", "Open again",
  "Source", "Institution", "Country",
];

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ ok: false, error: "request body is not JSON" });
  }

  let records = body.rows || [];
  if (TOKEN !== "CHANGE-ME" && body.token === TOKEN) {
    records = records.map(function (r) { return Object.assign({ source: "Web app" }, r); });
  } else if (COLAB_TOKEN !== "CHANGE-ME-COLAB" && body.token === COLAB_TOKEN) {
    records = records.slice(0, COLAB_MAX_ROWS).map(function (r) {
      return Object.assign({}, r, { source: "Colab" });
    });
  } else if (TOKEN === "CHANGE-ME") {
    return reply({ ok: false, error: "set TOKEN in the Apps Script first" });
  } else {
    return reply({ ok: false, error: "wrong token: it must equal TOKEN (website) or COLAB_TOKEN (notebook) in the Apps Script" });
  }

  const rows = records.map(toRow);
  if (rows.length === 0) return reply({ ok: true, added: 0 });

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const sheet = getSheet();
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, KEYS.length).setValues(rows);
  } finally {
    lock.releaseLock();
  }
  return reply({ ok: true, added: rows.length });
}

// Open the web app URL in a browser to check the deployment works.
function doGet() {
  return reply({ ok: true, message: "Render the Molecule recorder is running. The website sends rows here with POST." });
}

function toRow(record) {
  return KEYS.map(function (key) {
    const value = record[key];
    if (value === null || value === undefined) return "";
    if (key === "time") return new Date(value); // shown in the Sheet's own time zone
    return asText(value);
  });
}

// Text starting with = + - @ would run as a formula; a leading apostrophe keeps it plain text.
function asText(value) {
  if (typeof value === "string" && /^[=+\-@\t\r]/.test(value)) return "'" + value;
  return value;
}

function getSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(SHEET_NAME) || spreadsheet.insertSheet(SHEET_NAME);
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
    sheet.getRange("A:A").setNumberFormat("yyyy-mm-dd hh:mm:ss");
  } else if (sheet.getLastColumn() < HEADERS.length) {
    // Sheet made by an older version of this script: add the new column headers.
    sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
  }
  sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight("bold");
  return sheet;
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
