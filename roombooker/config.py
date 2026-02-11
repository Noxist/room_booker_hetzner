import os
from pathlib import Path

APP_DIR = Path(os.getenv("ROOMBOOKER_DATA_DIR", "/root/auto_reserve_data"))
BASE_DIR = APP_DIR # Alias für Kompatibilität
DEBUG_DIR = APP_DIR # Screenshots landen hier

SETTINGS_FILE = APP_DIR / "settings.json"
HISTORY_FILE = APP_DIR / "booking_history.json"
WEIGHTS_FILE = APP_DIR / "weights.json"
CATEGORIES_FILE = APP_DIR / "categories.json"
ROOMS_FILE = APP_DIR / "rooms.json"
JOBS_FILE = APP_DIR / "jobs.json"

# Kompatibilität für dein Skript
URL_LOGIN = "https://raumreservation.ub.unibe.ch/login"
URL_SELECT = "https://raumreservation.ub.unibe.ch/select"
URL_SET_VONROLL = "https://raumreservation.ub.unibe.ch/set/1"

URLS = {
    "base": "https://raumreservation.ub.unibe.ch",
    "login": URL_LOGIN,
    "event_add": "https://raumreservation.ub.unibe.ch/event/add"
}
HEADLESS = True
TIMEOUT = 60000
