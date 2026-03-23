# GitHub Data Mining & Visualization System

A **Producer-Consumer** system that mines popular GitHub repositories for function/method names, extracts word frequencies via AST parsing, and visualizes the results in a real-time dashboard.

## Architecture

```
┌─────────────────┐       shared volume       ┌────────────────────┐
│   Miner (Python) │ ───── /data/*.json ─────▶ │ Visualizer (Node)  │
│   FastAPI :5000  │                           │ Express+WS  :3000  │
│                  │ ◀── HTTP control API ──── │ Proxies  /api/*    │
└─────────────────┘                           └────────────────────┘
```

| Component   | Tech                | Port | Role                                   |
|-------------|---------------------|------|----------------------------------------|
| **Miner**   | Python 3.11 / FastAPI | 5000 | Fetches repos, parses AST, writes JSON |
| **Visualizer** | Node 20 / Express   | 3000 | Watches JSON files, serves dashboard   |

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/install/)
- A [GitHub Personal Access Token](https://github.com/settings/tokens) (classic, with `public_repo` scope) for rate-limit handling

## Quick Start

### 1. Clone & configure

```bash
git clone <repo-url>
cd TareaDiagnosticaDatos

# Create your .env from the template
cp .env.template .env
# Edit .env and paste your GitHub token
```

### 2. Build & run

```bash
docker-compose up --build
```

### 3. Open the dashboard

Navigate to **http://localhost:3000** in your browser.

### 4. Control the miner

- Click **▶ Start Miner** to begin mining popular Python/Java repositories.
- Click **■ Stop Miner** to gracefully pause after the current repo finishes.
- Adjust the **Top-N** slider to show more or fewer words in the histogram.
- The chart updates in **real-time** as new repository data is processed.

## API Endpoints (Miner)

| Method | Endpoint  | Description                                  |
|--------|-----------|----------------------------------------------|
| GET    | `/status` | Returns `{ "status": "idle" \| "mining" \| "stopping" }` |
| POST   | `/start`  | Starts mining in a background thread         |
| POST   | `/stop`   | Signals a graceful stop (no container exit)   |

These are also accessible through the Visualizer's proxy: `/api/miner/status`, `/api/miner/start`, `/api/miner/stop`.

## How It Works

### Miner
1. Searches GitHub for the most-starred Python + Java repositories.
2. For each repo, uses the **Trees API** (`recursive=1`) to get the complete file listing.
3. Filters for `.py` / `.java` files, excluding vendor directories (`venv/`, `node_modules/`, etc.).
4. Fetches file content via the **Blobs API** (base64-decoded).
5. Parses function/method names:
   - **Python**: `ast` module (standard library)
   - **Java**: regex-based method declaration matching
6. Splits names into words (handles `camelCase`, `PascalCase`, `snake_case`).
7. Writes `owner_repo-name.json` atomically to the shared volume.
8. On resume, skips repos whose JSON already exists.

### Visualizer
1. On startup, loads all existing `.json` files from the shared volume.
2. Watches for new files using **chokidar**.
3. Merges word counts into a global aggregate.
4. Pushes updates to all connected browsers via **WebSocket**.
5. Frontend renders a horizontal bar chart with **Chart.js**.

## Data Format

Each `.json` file follows this structure:

```json
{
  "repo": "owner/repo-name",
  "words": {
    "create": 42,
    "update": 35,
    "validate": 28
  }
}
```

## Stopping & Restarting

- **Stop the miner** via the UI or `POST http://localhost:5000/stop`. The container stays alive (no `sys.exit()`).
- **Restart mining** via the UI or `POST http://localhost:5000/start`. Already-mined repos are skipped automatically.
- **Stop everything**: `docker-compose down` (data persists in the `shared_data` volume).
- **Full reset**: `docker-compose down -v` (deletes the volume and all mined data).

## Project Structure

```
TareaDiagnosticaDatos/
├── docker-compose.yml
├── .env.template
├── .env                  # your token (git-ignored)
├── README.md
├── miner/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py            # FastAPI server
│   └── mining.py         # GitHub API + AST logic
└── visualizer/
    ├── Dockerfile
    ├── package.json
    ├── server.js          # Express + WebSocket + chokidar
    └── public/
        └── index.html     # Dashboard UI
```
