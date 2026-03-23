/**
 * server.js – Express + WebSocket server for the Visualizer.
 *
 * - Serves the static frontend from ./public
 * - Watches /data for new .json files via chokidar
 * - Broadcasts aggregated word counts to WebSocket clients in real-time
 * - Proxies /api/miner/* requests to the Miner container
 */

const express = require("express");
const http = require("http");
const { WebSocketServer } = require("ws");
const chokidar = require("chokidar");
const fs = require("fs");
const path = require("path");

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

const DATA_DIR = process.env.DATA_DIR || "/data";
const MINER_URL = process.env.MINER_URL || "http://miner:5000";
const PORT = process.env.PORT || 3000;

// ─── In-memory aggregated word counts ────────────────────────────────

/** @type {Record<string, number>} */
let globalWords = {};

/** @type {Set<string>} */
const ingestedFiles = new Set();

/**
 * Ingest a single JSON file and merge its word counts into the global map.
 * @param {string} filePath
 */
function ingestFile(filePath) {
  const basename = path.basename(filePath);
  if (ingestedFiles.has(basename)) return;

  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    const data = JSON.parse(raw);
    const words = data.words || {};

    for (const [word, count] of Object.entries(words)) {
      globalWords[word] = (globalWords[word] || 0) + count;
    }

    ingestedFiles.add(basename);
    console.log(`[ingest] ${basename} (${Object.keys(words).length} words)`);
    broadcastUpdate();
  } catch (err) {
    console.error(`[ingest] Failed to parse ${basename}:`, err.message);
  }
}

/**
 * Broadcast the current global word counts to all connected WebSocket clients.
 */
function broadcastUpdate() {
  const payload = JSON.stringify({
    type: "update",
    words: globalWords,
    repoCount: ingestedFiles.size,
  });
  for (const client of wss.clients) {
    if (client.readyState === 1 /* OPEN */) {
      client.send(payload);
    }
  }
}

// ─── Load existing files on startup ──────────────────────────────────

function loadExistingFiles() {
  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    const files = fs.readdirSync(DATA_DIR).filter((f) => f.endsWith(".json"));
    for (const file of files) {
      ingestFile(path.join(DATA_DIR, file));
    }
    console.log(`[startup] Loaded ${files.length} existing file(s)`);
  } catch (err) {
    console.error("[startup] Error loading existing files:", err.message);
  }
}

loadExistingFiles();

// ─── Watch for new files ─────────────────────────────────────────────

const watcher = chokidar.watch(path.join(DATA_DIR, "*.json"), {
  persistent: true,
  ignoreInitial: true,
  awaitWriteFinish: { stabilityThreshold: 500, pollInterval: 100 },
});

watcher.on("add", (filePath) => {
  console.log(`[watch] New file detected: ${path.basename(filePath)}`);
  ingestFile(filePath);
});

watcher.on("error", (err) => {
  console.error("[watch] Error:", err.message);
});

// ─── WebSocket connections ───────────────────────────────────────────

wss.on("connection", (ws) => {
  console.log("[ws] Client connected");
  // Send the current state immediately
  ws.send(
    JSON.stringify({
      type: "update",
      words: globalWords,
      repoCount: ingestedFiles.size,
    })
  );
});

// ─── Static files ────────────────────────────────────────────────────

app.use(express.static(path.join(__dirname, "public")));

// ─── Miner proxy endpoints ──────────────────────────────────────────

/**
 * Proxy helper – forwards a request to the Miner's API.
 */
async function proxyToMiner(minerPath, method, res) {
  try {
    const url = `${MINER_URL}${minerPath}`;
    const resp = await fetch(url, { method });
    const body = await resp.text();
    res.status(resp.status).set("Content-Type", "application/json").send(body);
  } catch (err) {
    console.error(`[proxy] Error contacting miner at ${minerPath}:`, err.message);
    res.status(502).json({ error: "Could not reach miner service" });
  }
}

app.post("/api/miner/start", (_req, res) => proxyToMiner("/start", "POST", res));
app.post("/api/miner/stop", (_req, res) => proxyToMiner("/stop", "POST", res));
app.get("/api/miner/status", (_req, res) => proxyToMiner("/status", "GET", res));

// ─── Start server ───────────────────────────────────────────────────

server.listen(PORT, () => {
  console.log(`[server] Visualizer running on http://0.0.0.0:${PORT}`);
});
