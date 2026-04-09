// Stdlib-only Node.js backend — no npm packages required
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const DATA = path.join(ROOT, "data");
const SCRIPTS = path.join(ROOT, "validation_scripts");

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return [];
  }
}

const ROUTES = {
  "/api/rules":      () => readJson(path.join(DATA, "rules.json")),
  "/api/violations": () => readJson(path.join(DATA, "violations.json")),
  "/api/audit":      () => readJson(path.join(DATA, "audit_log.json")),
  "/api/scripts":    () => {
    if (!fs.existsSync(SCRIPTS)) return [];
    return fs.readdirSync(SCRIPTS)
      .filter(f => f.endsWith(".py"))
      .map(f => ({ name: f, path: path.join(SCRIPTS, f) }));
  },
};

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "*",
};

const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0];

  Object.assign(res, { jsonSend(data, status = 200) {
    const body = JSON.stringify(data);
    res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body), ...CORS });
    res.end(body);
  }});

  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS);
    return res.end();
  }

  if (ROUTES[url] && req.method === "GET") {
    return res.jsonSend(ROUTES[url]());
  }

  if (req.method === "POST") {
    return res.jsonSend({ status: "ok", message: "Stub — run agents manually via CLI" });
  }

  res.writeHead(404, CORS);
  res.end("Not found");
});

const PORT = 8000;
server.listen(PORT, "127.0.0.1", () => {
  console.log(`ADIE backend running at http://127.0.0.1:${PORT}`);
});
