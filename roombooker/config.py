import os
import json
from pathlib import Path

# Docker data directory path
BASE_DIR = Path(os.getenv("ROOMBOOKER_DATA_DIR", "/home/leandro/auto_reserve_data"))
BASE_DIR.mkdir(parents=True, exist_ok=True)

# File paths
SETTINGS_FILE = BASE_DIR / "settings.json"
HISTORY_FILE = BASE_DIR / "booking_history.json"
WEIGHTS_FILE = BASE_DIR / "weights.json"
CATEGORIES_FILE = BASE_DIR / "categories.json"
CREDENTIALS_FILE = BASE_DIR / "google_credentials.json"
JOBS_FILE = BASE_DIR / "jobs.json"
STATUS_FILE = BASE_DIR / "web_status.txt"
LINKS_FILE = BASE_DIR / "links.json"
DISTANCE_MATRIX_FILE = BASE_DIR / "roomDistanceMatrix.json"
DEBUG_DIR = BASE_DIR / "debug_scans"
DEBUG_DUMPS_DIR = BASE_DIR / "debug_dumps"
LOG_FILE = BASE_DIR / "logs" / "app.log"

# Ensure directories exist
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DUMPS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# --- Load URLs from links.json (no more hardcoding) ---
def _load_links():
    defaults = {
        "base_url": "https://raumreservation.ub.unibe.ch",
        "login_url": "https://raumreservation.ub.unibe.ch/event/add",
        "event_add_url": "https://raumreservation.ub.unibe.ch/event/add",
        "my_reservations_url": "https://raumreservation.ub.unibe.ch/reservation",
        "set_location_vonroll_url": "https://raumreservation.ub.unibe.ch/set/1",
        "grid_view_base_url": "https://raumreservation.ub.unibe.ch/event?day=",
    }
    if LINKS_FILE.exists():
        try:
            with open(LINKS_FILE, "r") as f:
                loaded = json.load(f)
                defaults.update(loaded)
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load links.json: {e}")
    return defaults

_LINKS = _load_links()

URL_LOGIN = _LINKS["login_url"]
URL_EVENT_ADD = _LINKS["event_add_url"]
URL_SELECT = _LINKS["base_url"] + "/select"
URL_SET_VONROLL = _LINKS["set_location_vonroll_url"]
URL_GRID_BASE = _LINKS["grid_view_base_url"]
URL_MY_RESERVATIONS = _LINKS["my_reservations_url"]

# --- Load weights from weights.json ---
def load_weights():
    defaults = {
        "totalCoveredMin": 0.003,
        "waitPenalty": -1.581,
        "switchBonus": -0.032,
        "stabilityBonus": 0.5,
        "productiveLossMin": -0.122,
    }
    if WEIGHTS_FILE.exists():
        try:
            with open(WEIGHTS_FILE, "r") as f:
                loaded = json.load(f)
                defaults.update(loaded)
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load weights.json: {e}")
    return defaults

# --- Load room distance matrix ---
def load_distance_matrix():
    if DISTANCE_MATRIX_FILE.exists():
        try:
            with open(DISTANCE_MATRIX_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load roomDistanceMatrix.json: {e}")
    return {}

# --- Load excessive_logging toggle from settings.json ---
def get_excessive_logging():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("excessive_logging", False)
        except:
            pass
    return False

# Browser settings
HEADLESS = True
