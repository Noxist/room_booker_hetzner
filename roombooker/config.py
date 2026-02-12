import os
from pathlib import Path

# Im Docker ist das Datenverzeichnis immer hier:
BASE_DIR = Path("/root/auto_reserve_data")
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Datei-Pfade
SETTINGS_FILE = BASE_DIR / "settings.json"
HISTORY_FILE = BASE_DIR / "booking_history.json"
WEIGHTS_FILE = BASE_DIR / "weights.json"
CATEGORIES_FILE = BASE_DIR / "categories.json"
CREDENTIALS_FILE = BASE_DIR / "google_credentials.json"
JOBS_FILE = BASE_DIR / "jobs.json"
STATUS_FILE = BASE_DIR / "web_status.txt"
DEBUG_DIR = BASE_DIR / "debug_scans"

DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# URLs
URL_LOGIN = "https://raumreservation.ub.unibe.ch/event/add"
URL_SELECT = "https://raumreservation.ub.unibe.ch/select"
URL_SET_VONROLL = "https://raumreservation.ub.unibe.ch/set/1"
HEADLESS = True
