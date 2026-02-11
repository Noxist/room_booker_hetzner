import os
from pathlib import Path

APP_DIR = Path(os.getenv("ROOMBOOKER_DATA_DIR", "/root/auto_reserve_data"))
SETTINGS_FILE = APP_DIR / "settings.json"
HISTORY_FILE = APP_DIR / "booking_history.json"
WEIGHTS_FILE = APP_DIR / "weights.json"
CATEGORIES_FILE = APP_DIR / "categories.json"
ROOMS_FILE = APP_DIR / "rooms.json"
JOBS_FILE = APP_DIR / "jobs.json"

URLS = {
    "base": "https://raumreservation.ub.unibe.ch",
    "event_add": "https://raumreservation.ub.unibe.ch/event/add"
}
HEADLESS = True
