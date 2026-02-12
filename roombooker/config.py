import os
from pathlib import Path

# Pfad-Erkennung (Host vs Docker)
if os.path.exists("/.dockerenv"):
    BASE_DIR = Path("/root/auto_reserve_data")
    HEADLESS = True
else:
    BASE_DIR = Path("/home/leandro/auto_reserve_data")
    HEADLESS = True

BASE_DIR.mkdir(parents=True, exist_ok=True)
APP_DIR = BASE_DIR
DEBUG_DIR = BASE_DIR

SETTINGS_FILE = BASE_DIR / "settings.json"
HISTORY_FILE = BASE_DIR / "booking_history.json"
WEIGHTS_FILE = BASE_DIR / "weights.json"
CATEGORIES_FILE = BASE_DIR / "categories.json"
ROOMS_FILE = BASE_DIR / "rooms.json"
JOBS_FILE = BASE_DIR / "jobs.json"
GOOGLE_CREDS = BASE_DIR / "google_credentials.json"
GOOGLE_TOKEN = BASE_DIR / "token.json"

# Die URLs, die deine browser.py importiert
URL_BASE = "https://raumreservation.ub.unibe.ch"
URL_LOGIN = f"{URL_BASE}/login"
URL_SELECT = f"{URL_BASE}/select"
URL_SET_VONROLL = f"{URL_BASE}/set/1"

URLS = {
    "base": URL_BASE,
    "login": URL_LOGIN,
    "event_add": f"{URL_BASE}/event/add"
}

TIMEOUT = 60000
