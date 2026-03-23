Act as an expert Full-Stack Software Engineer and DevOps Architect. Your task is to develop a data mining and visualization system using a Producer-Consumer architecture with file-based persistent storage.

The system consists of two main components (Miner and Visualizer) that must be fully containerized. Please provide the complete source code, Dockerfiles, a docker-compose.yml file, and a README.md with execution instructions and documentation.

### 1. Architecture & Infrastructure
* **Storage Protocol:** Use a shared Docker Volume. The Miner will write output as JSON files to this volume, and the Visualizer will read from it.
* **Containerization:** Orchestrate the Miner and Visualizer via `docker-compose.yml`.

### 2. Miner Component (Producer)
* **Language:** Python.
* **Data Source:** GitHub REST API or GraphQL. Fetch Python and Java repositories in descending order of popularity (by star count).
* **Authentication:** Must accept a `GITHUB_TOKEN` environment variable for Personal Access Token authentication to handle rate limits.
* **Execution & Control:**
    * **State Management:** The Miner must start in an **IDLE/OFF** state by default. It must not mine anything until explicitly instructed.
    * **API Endpoints:** Expose a lightweight HTTP API (e.g., using Flask or FastAPI) on a dedicated port with `/start`, `/stop`, and `/status` endpoints.
    * **Start/Stop Logic:** The `/start` endpoint should begin the continuous mining loop in a background thread. The `/stop` endpoint must signal the Miner to finish processing the *current* repository and then pause mining. **Crucially, the script must NOT exit (e.g., no `sys.exit(0)`) after stopping, so the container stays alive and avoids automatic Docker restart loops.**
    * **Resumption Logic:** Before fetching a repository's source code, check the shared volume. If a JSON file for that repository already exists, gracefully skip it and move to the next to avoid redundant processing.
* **Processing Efficiency:** 
    * **Avoid Indiscriminate Downloads:** Do NOT download the entire repository source archive (to save bandwidth). 
    * **Avoid Individual File Polling:** Do NOT iterate through files one-by-one with separate `raw.githubusercontent` requests (to save overhead).
    * **Targeted Extraction Logic:** 
        1. Use the **Trees API** (`recursive=1`) to get the full file list and their unique `sha` hashes.
        2. Filter the tree locally for relevant `.py` and `.java` files, excluding common vendor/binary directories.
        3. Fetch the content of ONLY these filtered files. Use the **Blobs API** or the **Contents API** if the files are small, or explore fetching them in minimal batches if possible.
    * **Filtering:** Parse ONLY files with `.py` or `.java` extensions. Avoid parsing known large vendor folders (e.g., `venv/`, `vendor/`, `node_modules/`).
    * **AST Extraction:** Reliably find function and method names. Split names into individual words respecting `camelCase` and `snake_case`.
* **Output Format:** Save a valid `.json` file for each repository in the shared volume (e.g., `owner_repo-name.json`). Format strictly as:
    { 
      "repo": "owner/repo-name",
      "words": {
        "word1": 10,
        "word2": 20
      }
    }

### 3. Visualizer Component (Consumer)
* **Language/Tech Stack:** JavaScript (Node.js backend + HTML/JS frontend).
* **Data Ingestion:** The Node.js backend must watch the shared Docker volume for new `.json` files (e.g., using `chokidar` or a similar file-watching library) and ingest the data as files are created.
* **Control Panel:** 
    * The frontend must include "Start Miner" and "Stop Miner" controls that trigger the respective endpoints on the Miner component (proxied via the Node.js backend if necessary). 
    * The frontend must query the Miner's `/status` endpoint on initial page load to correctly set the UI state (e.g. status indicator, disabled buttons), avoiding state reset illusions on page refresh.
* **Visualization:**
    * Display a horizontal histogram of the global word rankings using a library like Chart.js or D3.js.
    * **Important UI Fix:** Ensure the canvas or its wrapper has an explicitly defined structural `height` in CSS (or dynamically managed via JS), rather than relying solely on `min-height`, which causes display bugs (zero height) with responsive rendering in popular chart libraries.
    * Update the visualization in real-time as new files are detected (push data from backend to frontend via WebSockets or Server-Sent Events).
    * Make the ranking parameterizable (e.g., a UI input to easily adjust the "Top-N" words displayed).

Ensure the code is clean, includes proper error handling, and strictly adheres to the AST parsing requirements and graceful shutdown logic.