/**
 * Render the Molecule → Google Sheet recorder.
 *
 * Paste this into Extensions → Apps Script of a Google Sheet, change TOKEN,
 * and deploy it as a web app (step-by-step in the README, section
 * "Record who rendered what in a Google Sheet").
 * Each render the website finishes is appended as one row to the "Renders" tab.
 */

// Choose a long random password. Put the same value in the SHEET_TOKEN secret of the Space.
const TOKEN = "CHANGE-ME";

const SHEET_NAME = "Renders";

// Column order; must match ROW_KEYS in app/sheet.py.
const KEYS = [
  "time", "name", "email", "pdb_id", "style", "color", "material", "viewpoint",
  "resolution", "quality", "background", "ligands", "assembly",
  "status", "cached", "render_s", "error", "link",
];
const HEADERS = [
  "Time", "Name", "Email", "PDB ID", "Style", "Colour", "Material", "View",
  "Size", "Quality", "Background", "Ligands", "Assembly",
  "Status", "From cache", "Render time (s)", "Error", "Open again",
];

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ ok: false, error: "request body is not JSON" });
  }
  if (TOKEN === "CHANGE-ME") return reply({ ok: false, error: "set TOKEN in the Apps Script first" });
  if (body.token !== TOKEN) return reply({ ok: false, error: "wrong token: SHEET_TOKEN must equal TOKEN in the Apps Script" });

  const rows = (body.rows || []).map(toRow);
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
    sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight("bold");
    sheet.getRange("A:A").setNumberFormat("yyyy-mm-dd hh:mm:ss");
  }
  return sheet;
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
