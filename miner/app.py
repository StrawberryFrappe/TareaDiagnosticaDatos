"""
app.py – FastAPI application for the GitHub repository miner.

Exposes /start, /stop, and /status endpoints to control a background
mining thread.  Starts in IDLE state (no mining until /start is called).
"""

import logging
import threading

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from mining import mine_repos

# ─── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("miner")

# ─── Application state ───────────────────────────────────────────────

app = FastAPI(title="GitHub Miner API")

_lock = threading.Lock()
_stop_event = threading.Event()
_mining_thread: threading.Thread | None = None
_status: str = "idle"  # "idle" | "mining" | "stopping"


def _mining_wrapper():
    """Wrapper that runs the mining loop and resets state when done."""
    global _status
    try:
        mine_repos(_stop_event)
    except Exception:
        logger.exception("Mining loop crashed")
    finally:
        with _lock:
            _status = "idle"
        logger.info("Mining thread finished – status set to idle")


# ─── Endpoints ────────────────────────────────────────────────────────

@app.get("/status")
def status():
    """Return the current miner status."""
    return JSONResponse({"status": _status})


@app.post("/start")
def start():
    """Start the mining loop in a background thread."""
    global _mining_thread, _status

    with _lock:
        if _status == "mining":
            return JSONResponse(
                {"message": "Miner is already running", "status": _status},
                status_code=409,
            )

        _stop_event.clear()
        _status = "mining"
        _mining_thread = threading.Thread(target=_mining_wrapper, daemon=True)
        _mining_thread.start()

    logger.info("Mining started")
    return JSONResponse({"message": "Mining started", "status": "mining"})


@app.post("/stop")
def stop():
    """Signal the miner to stop after finishing the current repository."""
    global _status

    with _lock:
        if _status != "mining":
            return JSONResponse(
                {"message": "Miner is not running", "status": _status},
                status_code=409,
            )
        _status = "stopping"

    _stop_event.set()
    logger.info("Stop signal sent – miner will finish current repo and pause")
    return JSONResponse({"message": "Stop signal sent", "status": "stopping"})
