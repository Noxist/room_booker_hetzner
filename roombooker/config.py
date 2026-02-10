import os
import sys
from pathlib import Path

APP_NAME = "Room Booker Ultimate"

def get_install_dir() -> Path:
    return Path(__file__).resolve().parent.parent

# --- AUTO ENV LOAD ---
# Lädt .env Variablen, falls lokal ausgeführt (für Google Cal ID)
env_path = get_install_dir() / ".env"
if env_path.exists():
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                # Nur setzen wenn nicht schon da (Docker hat Vorrang)
                if key not in os.environ:
                    os.environ[key] = val.strip().strip('"').strip("'")

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

def get_data_dir() -> Path:
    # 1. Lokaler 'data' Ordner
    if os.path.exists("data"): return Path("data").resolve()
    # 2. Env Var
    if os.environ.get("ROOMBOOKER_DATA_DIR"): return Path(os.environ["ROOMBOOKER_DATA_DIR"])
    # 3. Docker Default
    if os.path.exists("/app/data"): return Path("/app/data")
    # 4. Fallback
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) if sys.platform.startswith("win") else Path.home() / ".config"
    return base / "RoomBooker"

APP_DIR = get_data_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = APP_DIR / "settings.json"
ROOMS_FILE = APP_DIR / "rooms.json"
BLUEPRINTS_FILE = APP_DIR / "blueprints.json"
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "room_booker.log"
CSV_EXPORT_FILE = APP_DIR / "alle_reservationen.csv"

# Browser Pfad setzen
PLAYWRIGHT_BROWSERS_PATH = APP_DIR / "playwright"
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_PATH)

def get_version() -> str:
    try:
        v_file = get_install_dir() / "version.txt"
        if v_file.exists(): return v_file.read_text(encoding="utf-8").strip()
    except: pass
    return "0.0.0"
