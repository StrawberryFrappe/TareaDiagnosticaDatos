"""
mining.py – Core mining logic for the GitHub repository miner.

Fetches popular Python/Java repos from GitHub, extracts function/method names
via AST parsing, splits them into words, and writes per-repo JSON files to
the shared data volume.
"""

import ast
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from threading import Event

import requests

logger = logging.getLogger("miner")

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Directories to skip when filtering the file tree
EXCLUDED_DIRS = {
    "venv", ".venv", "env", ".env", "vendor", "node_modules",
    "__pycache__", ".git", "build", "dist", "target", "site-packages",
    ".tox", ".mypy_cache", ".pytest_cache", "eggs", ".eggs",
}

# Python keywords / builtins to exclude from word counts
STOP_WORDS = {
    "self", "cls", "none", "true", "false", "return", "def", "class",
    "import", "from", "if", "else", "elif", "try", "except", "finally",
    "for", "while", "with", "as", "in", "is", "not", "and", "or",
    "pass", "break", "continue", "raise", "yield", "lambda", "global",
    "nonlocal", "assert", "del", "print", "len", "range", "list",
    "dict", "set", "str", "int", "float", "bool", "type", "super",
    "object", "init", "new", "main", "test", "get", "set",
    "the", "this", "that", "args", "kwargs", "var", "val",
    "void", "public", "private", "protected", "static", "final",
    "abstract", "class", "interface", "extends", "implements",
    "package", "import", "throws", "throw", "catch", "try",
    "synchronized", "volatile", "transient", "native", "instanceof",
    "enum", "override", "deprecated", "string", "integer", "boolean",
    "null", "byte", "short", "long", "double", "char",
}

# ─── GitHub API helpers ───────────────────────────────────────────────

def _headers():
    """Build request headers, including auth if a token is available."""
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def _handle_rate_limit(resp: requests.Response):
    """Sleep until the rate-limit resets if we are close to the limit."""
    remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
    if remaining < 5:
        reset_ts = int(resp.headers.get("X-RateLimit-Reset", 0))
        sleep_for = max(reset_ts - int(time.time()), 0) + 2
        logger.warning("Rate limit nearly exhausted – sleeping %ds", sleep_for)
        time.sleep(sleep_for)


def _get(url: str, params: dict | None = None, stop_event: Event | None = None):
    """Perform a GET request with retry on transient errors."""
    for attempt in range(3):
        if stop_event and stop_event.is_set():
            return None
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=30)
            if resp.status_code == 403:
                _handle_rate_limit(resp)
                continue
            resp.raise_for_status()
            _handle_rate_limit(resp)
            return resp
        except requests.RequestException as exc:
            logger.warning("Request failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(2 ** attempt)
    return None


# ─── Repository discovery ────────────────────────────────────────────

def fetch_repos(page: int = 1, per_page: int = 30, stop_event: Event | None = None):
    """Return a page of popular Python + Java repos sorted by stars."""
    url = "https://api.github.com/search/repositories"
    params = {
        "q": "language:python language:java",
        "sort": "stars",
        "order": "desc",
        "page": page,
        "per_page": per_page,
    }
    resp = _get(url, params=params, stop_event=stop_event)
    if resp is None:
        return []
    data = resp.json()
    return data.get("items", [])


# ─── Tree / Blob fetching ────────────────────────────────────────────

def _is_excluded(path: str) -> bool:
    """Check if a path falls inside an excluded directory."""
    parts = path.split("/")
    return any(p in EXCLUDED_DIRS for p in parts)


def fetch_file_tree(owner: str, repo: str, default_branch: str,
                    stop_event: Event | None = None):
    """Use the Trees API (recursive) to get the full list of blobs."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}"
    resp = _get(url, params={"recursive": "1"}, stop_event=stop_event)
    if resp is None:
        return []
    tree = resp.json().get("tree", [])
    relevant = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if _is_excluded(path):
            continue
        if path.endswith(".py") or path.endswith(".java"):
            relevant.append(item)
    return relevant


def fetch_blob_content(owner: str, repo: str, sha: str,
                       stop_event: Event | None = None) -> str | None:
    """Fetch a single blob via the Blobs API and base64-decode it."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{sha}"
    resp = _get(url, stop_event=stop_event)
    if resp is None:
        return None
    blob = resp.json()
    encoding = blob.get("encoding", "")
    content = blob.get("content", "")
    if encoding == "base64":
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return None
    return content


# ─── AST / name extraction ───────────────────────────────────────────

def extract_python_names(source: str) -> list[str]:
    """Extract function and method names from Python source using the ast module."""
    names: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
    return names


# Regex to match Java method declarations (good-enough heuristic)
_JAVA_METHOD_RE = re.compile(
    r'(?:public|private|protected|static|final|abstract|synchronized|native|\s)+'
    r'[\w<>\[\],\s]+\s+'          # return type
    r'(\w+)'                       # method name (capture group 1)
    r'\s*\(',                      # opening parenthesis
)


def extract_java_names(source: str) -> list[str]:
    """Extract method names from Java source using regex."""
    return _JAVA_METHOD_RE.findall(source)


# ─── Word splitting ──────────────────────────────────────────────────

def split_name(name: str) -> list[str]:
    """
    Split a function/method name into individual words.
    Handles snake_case, camelCase, PascalCase, and mixed styles.
    """
    # Replace underscores with spaces
    name = name.replace("_", " ")
    # Insert space before uppercase letters preceded by a lowercase letter (camelCase)
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    # Insert space between consecutive uppercase letters followed by lowercase (e.g. XMLParser)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    words = name.lower().split()
    # Filter: keep only alphabetic words of length > 1 that are not stop words
    return [w for w in words if w.isalpha() and len(w) > 1 and w not in STOP_WORDS]


# ─── Main mining loop ────────────────────────────────────────────────

def _json_filename(full_name: str) -> str:
    """Convert 'owner/repo-name' to 'owner_repo-name.json'."""
    return full_name.replace("/", "_") + ".json"


def mine_repos(stop_event: Event):
    """
    Continuously mine repositories until the stop event is set.
    Writes one JSON file per repository to DATA_DIR.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    page = 1

    while not stop_event.is_set():
        repos = fetch_repos(page=page, per_page=30, stop_event=stop_event)
        if not repos:
            logger.info("No more repos returned on page %d – restarting from page 1", page)
            page = 1
            time.sleep(5)
            continue

        for repo_info in repos:
            if stop_event.is_set():
                logger.info("Stop signal received – finishing current batch")
                return

            full_name = repo_info.get("full_name", "")
            default_branch = repo_info.get("default_branch", "main")
            out_file = DATA_DIR / _json_filename(full_name)

            # ── Skip if already mined ──
            if out_file.exists():
                logger.info("Skipping %s (already mined)", full_name)
                continue

            logger.info("Mining %s …", full_name)
            owner, repo_name = full_name.split("/", 1)

            # ── Fetch tree ──
            blobs = fetch_file_tree(owner, repo_name, default_branch,
                                    stop_event=stop_event)
            if stop_event.is_set():
                return

            word_counts: dict[str, int] = {}

            for blob_info in blobs:
                if stop_event.is_set():
                    return

                path = blob_info["path"]
                sha = blob_info["sha"]

                content = fetch_blob_content(owner, repo_name, sha,
                                             stop_event=stop_event)
                if content is None:
                    continue

                # ── Extract names ──
                if path.endswith(".py"):
                    names = extract_python_names(content)
                else:
                    names = extract_java_names(content)

                for name in names:
                    for word in split_name(name):
                        word_counts[word] = word_counts.get(word, 0) + 1

            # ── Write output ──
            result = {
                "repo": full_name,
                "words": dict(sorted(word_counts.items(),
                                     key=lambda x: x[1], reverse=True)),
            }
            try:
                # Write atomically: write to .tmp then rename
                tmp_file = out_file.with_suffix(".tmp")
                tmp_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
                tmp_file.rename(out_file)
                logger.info("Saved %s (%d unique words)", out_file.name,
                            len(word_counts))
            except OSError as exc:
                logger.error("Failed to write %s: %s", out_file.name, exc)

        page += 1
        # Small delay between pages to be friendly to the API
        time.sleep(1)

    logger.info("Mining loop stopped gracefully")
