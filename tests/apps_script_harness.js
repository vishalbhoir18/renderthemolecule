// Runs google-sheet/Code.gs in Node with stand-ins for SpreadsheetApp,
// LockService and ContentService. Used by tests/test_apps_script.py.
//
// stdin:  {"code": "<path to Code.gs>", "token": "...", "colab_token": "...",
//          "existing": [[...header...], ...], "posts": [<request body>, ...], "get": true}
// stdout: {"replies": [...], "rows": [[...], ...], "bold": bool}
const fs = require("fs");
const vm = require("vm");

const input = JSON.parse(fs.readFileSync(0, "utf8"));
let src = fs.readFileSync(input.code, "utf8");
src = src.replace('const TOKEN = "CHANGE-ME";', `const TOKEN = ${JSON.stringify(input.token)};`);
src = src.replace('const COLAB_TOKEN = "CHANGE-ME-COLAB";', `const COLAB_TOKEN = ${JSON.stringify(input.colab_token)};`);

const rows = (input.existing || []).map((r) => r.slice());
let exists = rows.length > 0;
let bold = false;
const sheet = {
  getLastRow: () => rows.length,
  getLastColumn: () => rows.reduce((m, r) => Math.max(m, r.length), 0),
  appendRow: (r) => rows.push(r.slice()),
  setFrozenRows: () => {},
  getRange: (...a) => {
    if (typeof a[0] === "string") return { setNumberFormat: () => {} };
    const [row, col, n, width] = a;
    return {
      setFontWeight: () => { bold = true; },
      setValues: (values) => {
        if (values.length !== n) throw new Error(`expected ${n} rows, got ${values.length}`);
        values.forEach((v, i) => {
          if (v.length !== width) throw new Error(`expected ${width} columns, got ${v.length}`);
          rows[row - 1 + i] = v.slice();
        });
      },
    };
  },
};
const context = {
  SpreadsheetApp: {
    getActiveSpreadsheet: () => ({
      getSheetByName: () => (exists ? sheet : null),
      insertSheet: () => { exists = true; return sheet; },
    }),
  },
  LockService: { getScriptLock: () => ({ waitLock: () => {}, releaseLock: () => {} }) },
  ContentService: {
    MimeType: { JSON: "json" },
    createTextOutput: (s) => ({ setMimeType: () => JSON.parse(s) }),
  },
  Date, JSON, Object,
};
vm.createContext(context);
vm.runInContext(src, context);

const replies = (input.posts || []).map((body) =>
  context.doPost({ postData: { contents: typeof body === "string" ? body : JSON.stringify(body) } }));
if (input.get) replies.push(context.doGet());
const plain = rows.map((r) => r.map((v) => (v instanceof Date ? { date: v.getTime() } : v)));
process.stdout.write(JSON.stringify({ replies, rows: plain, bold }));
