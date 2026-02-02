import os
import sys
from pathlib import Path

APP_NAME = "Room Booker Ultimate"
URLS = {
    "room_base": "https://raumreservation.ub.unibe.ch",
    "event_add": "https://raumreservation.ub.unibe.ch/event/add",
    "reservations": "https://raumreservation.ub.unibe.ch/reservation",
    "vonroll_location_path": "/set/1",
}

HARDCODED_ROOMS = {
    "vonRoll: Gruppenraum 001": "1",
    "vonRoll: Gruppenraum 002": "2",
    "vonRoll: Lounge": "11",
}


def get_app_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "RoomBooker"
    return Path.home() / ".config" / "RoomBooker"


def get_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_DIR = get_app_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = APP_DIR / "settings.json"
ROOMS_FILE = APP_DIR / "rooms.json"
BLUEPRINTS_FILE = APP_DIR / "blueprints.json"
PLAYWRIGHT_BROWSERS_PATH = APP_DIR / "playwright"
INSTALL_LOCK_FILE = APP_DIR / "playwright_install.lock"
DEBUG_DIR = APP_DIR / "debug_screenshots"
LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "room_booker.log"
CSV_EXPORT_FILE = APP_DIR / "alle_reservationen.csv"
LOGIC_OVERRIDE_FILE = APP_DIR / "logic_override.py"

DEBUG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

VERSION_FILE = get_install_dir() / "version.txt"

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_PATH)


def get_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "0.0.0"
