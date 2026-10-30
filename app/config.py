"""Configuration for Repo Graveyard."""
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

REPOS_CACHE_FILE = DATA_DIR / "repos_cache.json"
EPITAPHS_CACHE_FILE = DATA_DIR / "epitaphs_cache.json"
STORIES_CACHE_FILE = DATA_DIR / "stories_cache.json"
RESURRECT_CACHE_FILE = DATA_DIR / "resurrect_cache.json"

# Local LLM Configuration (Ollama)
# Single configuration line to swap models
OLLAMA_MODEL = os.getenv("REPO_GRAVEYARD_MODEL", "gemma3:4b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

# Hardware & Inference parameters
OLLAMA_KEEP_ALIVE = "10m"   # Keep model in VRAM for 10m
NUM_PREDICT_EPITAPH = 45    # 1-2 lines, short and punchy
NUM_PREDICT_STORY = 130     # ~80-100 words ghost story
NUM_PREDICT_RESURRECT = 260 # 3 concrete actionable steps
TEMPERATURE = 0.7

# Deterministic Classification Thresholds (in days since last commit)
ALIVE_DAYS_THRESHOLD = 30       # < 30 days
SLEEPING_DAYS_THRESHOLD = 180   # 30 to 180 days
DEAD_DAYS_THRESHOLD = 365       # 180 to 365 days
# > 365 days is classified as Ancient

# Scanner limits
SCAN_MAX_DEPTH = 3              # Max folder depth to search for git repos
SCAN_REPO_TIMEOUT = 5           # seconds per repo git extraction
IGNORED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", ".env",
    "__pycache__", ".idea", ".vscode", "vendor", "dist", "build",
    ".next", ".nuxt", "target", "bin", "obj", ".cargo", "AppData",
    "System Volume Information", "$RECYCLE.BIN"
}
