import csv
import json
import os
import queue
import random
import sys
import threading
import time
import importlib.util
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

import customtkinter as ctk
from tkinter import filedialog, messagebox
from playwright.sync_api import sync_playwright

# --- KONFIGURATION ---
APP_NAME = "Room Booker Ultimate"
VERSION_FILE = Path(__file__).resolve().parent / "version.txt"
ROOM_BASE_URL = "https://raumreservation.ub.unibe.ch"
EVENT_ADD_URL = f"{ROOM_BASE_URL}/event/add"
RESERVATIONS_URL = f"{ROOM_BASE_URL}/reservation"
VONROLL_LOCATION_PATH = "/set/1"

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


APP_DIR = get_app_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)

# --- DATEI-PFADE ---
SETTINGS_FILE = APP_DIR / "settings.json"
ROOMS_FILE = APP_DIR / "rooms.json"
BLUEPRINTS_FILE = APP_DIR / "blueprints.json"
PLAYWRIGHT_BROWSERS_PATH = APP_DIR / "playwright"
INSTALL_LOCK_FILE = APP_DIR / "playwright_install.lock"
DEBUG_DIR = APP_DIR / "debug_screenshots"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "room_booker.log"
CSV_EXPORT_FILE = APP_DIR / "alle_reservationen.csv"

# --- DIE MAGISCHE DEBUG-DATEI ---
DEBUG_LOGIC_FILE = APP_DIR / "debug_logic.py"

# WICHTIG: Pfad global setzen
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_PATH)


def get_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "0.0.0"


# --- HELPER ---

def human_type(page, selector: str, text: str) -> None:
    try:
        page.focus(selector)
        for char in text:
            page.keyboard.type(char, delay=random.randint(20, 60))
    except Exception:
        pass


def human_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


class OutputRedirector:
    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback

    def write(self, text: str):
        if text and text.strip():
            self.callback(text.strip())

    def flush(self):
        pass

    def isatty(self):
        return False


@dataclass
class Account:
    email: str = ""
    password: str = ""
    active: bool = True
    status: str = "Bereit"


@dataclass
class Job:
    date_mode: str
    date_value: str
    start_time: str
    end_time: str
    rooms: List[str]

    @property
    def label(self) -> str:
        if self.date_mode == "relative":
            return f"Relativ: {self.date_value}"
        return self.date_value

    def to_dict(self) -> Dict[str, object]:
        return {
            "date_mode": self.date_mode,
            "date_value": self.date_value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "rooms": list(self.rooms),
        }

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "Job":
        return Job(
            date_mode=data.get("date_mode", "single"),
            date_value=data.get("date_value", ""),
            start_time=data.get("start_time", "08:00"),
            end_time=data.get("end_time", "18:00"),
            rooms=list(data.get("rooms", [])),
        )


@dataclass
class Settings:
    accounts: List[Account] = field(default_factory=list)
    simulation: bool = True
    theme: str = "Dark"


class SettingsStore:
    @staticmethod
    def load() -> Settings:
        if not SETTINGS_FILE.exists():
            return Settings(accounts=[Account()])
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            accounts = [Account(**acc) for acc in data.get("accounts", [])]
            if not accounts:
                accounts = [Account()]
            return Settings(
                accounts=accounts,
                simulation=data.get("simulation", True),
                theme=data.get("theme", "Dark"),
            )
        except json.JSONDecodeError:
            return Settings(accounts=[Account()])

    @staticmethod
    def save(settings: Settings) -> None:
        data = {
            "accounts": [acc.__dict__ for acc in settings.accounts],
            "simulation": settings.simulation,
            "theme": settings.theme,
        }
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


class RoomStore:
    @staticmethod
    def load() -> Dict[str, str]:
        if ROOMS_FILE.exists():
            try:
                return json.loads(ROOMS_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    @staticmethod
    def save(room_map: Dict[str, str]) -> None:
        ROOMS_FILE.write_text(json.dumps(room_map, indent=2), encoding="utf-8")


class BlueprintStore:
    @staticmethod
    def load() -> Dict[str, List[Job]]:
        if not BLUEPRINTS_FILE.exists():
            return {}
        try:
            data = json.loads(BLUEPRINTS_FILE.read_text(encoding="utf-8"))
            return {name: [Job.from_dict(j) for j in jobs] for name, jobs in data.items()}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def save(blueprints: Dict[str, List[Job]]) -> None:
        payload = {name: [job.to_dict() for job in jobs] for name, jobs in blueprints.items()}
        BLUEPRINTS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class Logger:
    def __init__(self, queue_obj: "queue.Queue[str]", log_file: Path) -> None:
        self.queue = queue_obj
        self.log_file = log_file

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {message}"
        print(full_msg)
        try:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(full_msg + "\n")
        except Exception:
            pass
        self.queue.put(full_msg)


# --- WORKER LOGIK ---


class BookingWorker:
    def __init__(self, logger: Logger):
        self.logger = logger
        self.show_browser = False  # Wird von GUI gesteuert

    def get_context(self, p, session_path: Optional[Path] = None, *, force_visible: bool = False):
        headless_mode = False if force_visible else not self.show_browser

        self.logger.log(f"Starte Browser (Sichtbar: {self.show_browser})...")
        try:
            browser = p.chromium.launch(headless=headless_mode, slow_mo=50)
        except Exception as e:
            self.logger.log(f"Fehler Browser-Start: {e}")
            raise e

        args = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "viewport": {"width": 1300, "height": 900},
            "locale": "de-CH",
        }
        if session_path and session_path.exists():
            self.logger.log(f"Lade Session: {session_path.name}")
            args["storage_state"] = str(session_path)

        context = browser.new_context(**args)
        page = context.new_page()
        return browser, context, page

    def perform_login(self, page, email, password) -> bool:
        """
        Zentrale Login-Funktion basierend auf den Debug-Ergebnissen.
        """
        try:
            # 1. Startseite aufrufen
            if "/event/add" not in page.url:
                page.goto(EVENT_ADD_URL)
                page.wait_for_load_state("domcontentloaded")
            
            # 2. Standortwahl (Dropdown-Trick)
            if "/select" in page.url:
                self.logger.log("Standortwahl erkannt...")
                try:
                    # Erst Dropdown öffnen, falls vorhanden
                    if page.locator("#navbarDropDownRight").is_visible():
                        page.click("#navbarDropDownRight")
                        human_sleep(0.5)
                    
                    # Dann auf vonRoll klicken
                    page.click("a[href*='/set/1']")
                    page.wait_for_load_state("networkidle")
                except Exception as e:
                    self.logger.log(f"Warnung Standortwahl: {e}")

            human_sleep(1)

            # 3. Login Trigger (Timeline Klick)
            # Wir sind noch nicht eingeloggt (kein Logout-Button, URL hat kein 'login' aber wir sind auch nicht in der App)
            if "login" not in page.url and "wayf" not in page.url and "eduid" not in page.url:
                # Prüfen ob wir schon eingeloggt sind (User Menü sichtbar)
                if page.locator("#navbarUser").is_visible():
                    return True

                self.logger.log("Login-Trigger: Klicke auf Timeline...")
                try:
                    trigger = page.locator(".timeline-cell-clickable").first
                    if trigger.count() > 0:
                        trigger.click()
                    else:
                        page.mouse.click(700, 500)
                    
                    # Warten auf Redirect
                    time.sleep(3)
                except Exception as e:
                    self.logger.log(f"Fehler bei Login-Trigger: {e}")

            # 4. Edu-ID Login Prozess
            if "eduid" in page.url or page.locator("#username").is_visible():
                self.logger.log(f"Führe Login durch für {email}...")
                
                # Username
                page.fill("#username", email)
                human_sleep(0.5)
                if page.locator("button[name='_eventId_submit']").is_visible():
                    page.click("button[name='_eventId_submit']")
                else:
                    page.keyboard.press("Enter")
                
                human_sleep(1.5)

                # Password
                if page.locator("#password").is_visible():
                    page.fill("#password", password)
                    human_sleep(0.5)
                    if page.locator("button[name='_eventId_proceed']").is_visible():
                        page.click("button[name='_eventId_proceed']")
                    else:
                        page.keyboard.press("Enter")
                
                self.logger.log("Login abgeschickt. Warte auf Weiterleitung...")
                page.wait_for_load_state("networkidle")
                time.sleep(5) # Wichtig für Session-Aufbau

            # Check ob erfolgreich
            if page.locator("#navbarUser").is_visible() or "/event/add" in page.url:
                return True
            
            return False

        except Exception as e:
            self.logger.log(f"Fehler in perform_login: {e}")
            return False

    def update_room_list(self, email: str, password: str) -> Optional[Dict[str, str]]:
        try:
            with sync_playwright() as p:
                browser, _, page = self.get_context(p, force_visible=True)
                try:
                    self.logger.log("Starte Raum-Scan...")
                    if self.perform_login(page, email, password):
                        self.logger.log("Login OK. Scanne Räume...")
                        # Sicherstellen, dass wir auf der richtigen Seite sind
                        if "/event/add" not in page.url:
                            page.goto(EVENT_ADD_URL)
                            page.wait_for_load_state("domcontentloaded")
                        
                        human_sleep(2)
                        
                        js_data = page.evaluate(
                            """() => {
                            const sel = document.querySelector('#event_room');
                            if (!sel) return null;
                            const res = {};
                            for (let i = 0; i < sel.options.length; i++) {
                                const opt = sel.options[i];
                                if (opt.value && opt.value.trim() !== "") {
                                    res[opt.innerText.trim()] = opt.value;
                                }
                            }
                            return res;
                        }"""
                        )

                        if js_data and len(js_data) > 0:
                            self.logger.log(f"Scan erfolgreich: {len(js_data)} Räume.")
                            return js_data
                        
                        self.logger.log("Scan fehlgeschlagen (Liste leer?).")
                        return None
                    else:
                        self.logger.log("Login für Scan fehlgeschlagen.")
                        return None
                finally:
                    browser.close()
        except Exception as e:
            self.logger.log(f"CRITICAL: Playwright Crash: {e}")
            return None

    def fetch_reservations(self, accounts: List[Account]) -> None:
        all_reservations = []
        
        with sync_playwright() as p:
            for acc in accounts:
                if not acc.active or not acc.email:
                    continue
                    
                self.logger.log(f"Hole Reservationen für: {acc.email}")
                browser, context, page = self.get_context(p, force_visible=True) # Sichtbar lassen für Feedback
                
                try:
                    if self.perform_login(page, acc.email, acc.password):
                        self.logger.log(f"Gehe zu {RESERVATIONS_URL}...")
                        page.goto(RESERVATIONS_URL)
                        page.wait_for_load_state("networkidle")
                        human_sleep(1)
                        
                        rows = page.locator("table.table tbody tr").all()
                        count = 0
                        
                        if len(rows) > 0:
                            for row in rows:
                                cells = row.locator("td").all()
                                if len(cells) >= 4:
                                    # Daten extrahieren
                                    raw_time = " ".join(cells[0].inner_text().split())
                                    title = cells[1].inner_text().strip()
                                    location = cells[2].inner_text().strip()
                                    room = cells[3].inner_text().strip()
                                    
                                    all_reservations.append({
                                        "Account": acc.email,
                                        "Zeit": raw_time,
                                        "Titel": title,
                                        "Ort": location,
                                        "Raum": room,
                                        "Abgerufen_am": datetime.now().strftime("%d.%m.%Y %H:%M")
                                    })
                                    count += 1
                            self.logger.log(f"-> {count} Reservationen gefunden.")
                        else:
                            self.logger.log("-> Keine Reservationen in der Liste.")
                    else:
                        self.logger.log(f"-> Login fehlgeschlagen für {acc.email}")
                except Exception as e:
                    self.logger.log(f"Fehler beim Abruf: {e}")
                finally:
                    browser.close()
                    
        # CSV Speichern
        if all_reservations:
            try:
                keys = all_reservations[0].keys()
                with open(CSV_EXPORT_FILE, 'w', newline='', encoding='utf-8') as f:
                    dict_writer = csv.DictWriter(f, fieldnames=keys)
                    dict_writer.writeheader()
                    dict_writer.writerows(all_reservations)
                self.logger.log(f"ERFOLG: Alle Reservationen gespeichert in: {CSV_EXPORT_FILE}")
            except Exception as e:
                self.logger.log(f"Fehler beim Speichern der CSV: {e}")
        else:
            self.logger.log("Keine Reservationen zum Speichern gefunden.")

    def execute_booking(self, tasks, accounts, preferred_rooms, simulation_mode) -> None:
        self.logger.log("--- START: INTERNE BUCHUNG ---")
        if simulation_mode:
            self.logger.log("SIMULATIONS-MODUS (keine Buchung)")

        acc_idx = 0
        for task in tasks:
            block_success = False
            for room_name in preferred_rooms:
                if block_success:
                    break
                room_id = task["all_rooms"].get(room_name)
                if not room_id:
                    continue

                acc = accounts[acc_idx % len(accounts)]
                session_file = APP_DIR / f"session_{acc.email.replace('@','_')}.json"
                acc_idx += 1

                self.logger.log(f"Versuche: {task['start']}-{task['end']} ({room_name}) mit {acc.email}")

                try:
                    with sync_playwright() as p:
                        browser, context, page = self.get_context(p, session_path=session_file)
                        try:
                            # Wir nutzen die zentrale Login-Logik
                            if not self.perform_login(page, acc.email, acc.password):
                                self.logger.log("Login fehlgeschlagen.")
                                continue

                            # Session speichern
                            context.storage_state(path=str(session_file))

                            # Zurück zur Buchungsseite falls nötig
                            if "/event/add" not in page.url:
                                page.goto(EVENT_ADD_URL)
                                page.wait_for_load_state("domcontentloaded")

                            # Formular ausfüllen
                            page.evaluate(
                                "v => { var s=document.getElementById('event_room'); s.value=v; s.dispatchEvent(new Event('change')); }",
                                room_id,
                            )
                            human_sleep(0.5)
                            page.fill("#event_startDate", f"{task['date']} {task['start']}")
                            page.keyboard.press("Enter")
                            human_sleep(0.5)

                            t1 = datetime.strptime(task["start"], "%H:%M")
                            t2 = datetime.strptime(task["end"], "%H:%M")
                            dur = int((t2 - t1).total_seconds() / 60)

                            page.evaluate(
                                f"document.getElementById('event_duration').value = '{dur}'"
                            )
                            page.evaluate(
                                "document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))"
                            )
                            human_sleep(0.5)
                            human_type(page, "#event_title", "Lernen")

                            if page.is_visible('input[name="event[purpose]"][value="Other"]'):
                                page.check('input[name="event[purpose]"][value="Other"]')

                            if simulation_mode:
                                self.logger.log("SIMULATION OK.")
                                block_success = True
                            else:
                                self.logger.log("Speichere...")
                                page.click("#event_submit")
                                try:
                                    # Erfolgskriterium: URL ändert sich oder wir sind nicht mehr auf /add
                                    page.wait_for_url(lambda u: "/event/add" not in u, timeout=5000)
                                    self.logger.log(f"ERFOLG: {room_name} gebucht!")
                                    block_success = True
                                except Exception:
                                    # Prüfen auf Fehlermeldungen im Text
                                    content = page.content().lower()
                                    if "konflikt" in content or "belegt" in content:
                                         self.logger.log(f"Raum {room_name} ist belegt.")
                                    else:
                                         # Wenn wir immer noch auf der Seite sind, hat es wohl nicht geklappt
                                         if "/event/add" in page.url:
                                             self.logger.log(f"Fehler bei {room_name} (Keine Bestätigung).")
                                         else:
                                             # URL hat gewechselt -> Erfolg
                                             self.logger.log(f"ERFOLG: {room_name} gebucht!")
                                             block_success = True
                        finally:
                            browser.close()
                except Exception as e:
                    self.logger.log(f"Fehler bei Buchungsvorgang: {e}")

            if not block_success:
                self.logger.log(f"FEHLER: Block {task['start']} konnte nicht gebucht werden.")
            human_sleep(1)
        self.logger.log("--- PROZESS ENDE ---")


# --- INSTALLER ---


class PlaywrightInstaller:
    def __init__(self, logger: Logger):
        self.logger = logger
        self._install_lock = threading.Lock()

    def is_installed(self) -> bool:
        if not PLAYWRIGHT_BROWSERS_PATH.exists():
            return False
        return any(
            path.name.startswith("chromium") for path in PLAYWRIGHT_BROWSERS_PATH.iterdir() if path.is_dir()
        )

    def install(self, output_callback: Optional[Callable[[str], None]] = None) -> bool:
        if self._install_lock.locked():
            return False
        self._install_lock.acquire()
        try:
            PLAYWRIGHT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_PATH)

            orig_stdout, orig_stderr = sys.stdout, sys.stderr
            if output_callback:
                sys.stdout = sys.stderr = OutputRedirector(output_callback)

            old_argv = sys.argv
            sys.argv = ["playwright", "install", "chromium"]
            try:
                from playwright.__main__ import main as playwright_cli

                playwright_cli()
                return True
            except SystemExit as e:
                return e.code == 0
            except Exception as e:
                if output_callback:
                    output_callback(f"Error: {e}")
                return False
            finally:
                sys.stdout, sys.stderr = orig_stdout, orig_stderr
                sys.argv = old_argv
        finally:
            self._install_lock.release()


# --- GUI ---


class RoomBookerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {get_version()}")
        self.geometry("1300x850")
        self.log_queue = queue.Queue()
        self.logger = Logger(self.log_queue, LOG_FILE)
        self.worker = BookingWorker(self.logger)
        self.settings = SettingsStore.load()
        self.rooms = RoomStore.load() or HARDCODED_ROOMS
        self.blueprints = BlueprintStore.load()
        self.jobs: List[Job] = []
        ctk.set_appearance_mode(self.settings.theme)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_frames()
        self._show_frame("planner")
        self._start_log_pump()
        self.after(500, self._ensure_playwright_ready)

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=240, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(self.sidebar, text="Navigation", font=("", 18, "bold")).pack(pady=20)
        self.nav_buttons = {}
        for name, key in [
            ("Planer & Queue", "planner"),
            ("Meine Blueprints", "blueprints"),
            ("Accounts & Einstellungen", "accounts"),
        ]:
            btn = ctk.CTkButton(self.sidebar, text=name, command=lambda k=key: self._show_frame(k))
            btn.pack(fill="x", padx=20, pady=6)
            self.nav_buttons[key] = btn

        ctk.CTkFrame(self.sidebar, height=2).pack(fill="x", padx=20, pady=12)
        ctk.CTkLabel(self.sidebar, text="System Status", font=("", 14, "bold")).pack(pady=(0, 6))
        self.status_accounts = ctk.CTkLabel(self.sidebar, text="Accounts: 0")
        self.status_accounts.pack(anchor="w", padx=20)
        self.status_jobs = ctk.CTkLabel(self.sidebar, text="Jobs in Queue: 0")
        self.status_jobs.pack(anchor="w", padx=20, pady=(0, 6))

        ctk.CTkFrame(self.sidebar, height=2).pack(fill="x", padx=20, pady=12)
        ctk.CTkButton(self.sidebar, text="Beenden", fg_color="#8b1f1f", command=self.destroy).pack(
            side="bottom", fill="x", padx=20, pady=20
        )

    def _build_frames(self):
        self.frames = {
            n: ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
            for n in ["planner", "blueprints", "accounts"]
        }
        for frame in self.frames.values():
            frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self._build_planner_ui()
        self._build_blueprints_ui()
        self._build_accounts_ui()

    def _show_frame(self, name: str) -> None:
        for key, frame in self.frames.items():
            if key == name:
                frame.tkraise()
        self._refresh_status()

    def _build_planner_ui(self) -> None:
        frame = self.frames["planner"]
        ctk.CTkLabel(frame, text="Buchungs-Planer", font=("", 20, "bold")).pack(anchor="w")

        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="both", expand=True, pady=10)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)

        self.planer_left = ctk.CTkFrame(content)
        self.planer_left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.planer_right = ctk.CTkFrame(content)
        self.planer_right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        ctk.CTkLabel(self.planer_left, text="Neuen Auftrag konfigurieren", font=("", 16, "bold")).pack(
            anchor="w", padx=20, pady=(20, 10)
        )

        self.mode_var = ctk.StringVar(value="Einzel-Datum")
        mode_selector = ctk.CTkSegmentedButton(
            self.planer_left,
            values=["Einzel-Datum", "Wochentag (Serie)"],
            variable=self.mode_var,
            command=lambda _: self._toggle_date_mode(),
        )
        mode_selector.pack(fill="x", padx=20, pady=8)

        self.date_frame = ctk.CTkFrame(self.planer_left, fg_color="transparent")
        self.date_frame.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(self.date_frame, text="Datum (TT.MM.JJJJ)").pack(anchor="w")
        self.date_entry = ctk.CTkEntry(self.date_frame)
        self.date_entry.pack(fill="x", pady=5)
        self.date_entry.insert(0, date.today().strftime("%d.%m.%Y"))

        self.weekday_frame = ctk.CTkFrame(self.planer_left, fg_color="transparent")
        self.weekday_label = ctk.CTkLabel(self.weekday_frame, text="Wochentag (nächste 2 Wochen)")
        self.weekday_label.pack(anchor="w")
        self.weekday_var = ctk.StringVar(value="Montag")
        self.weekday_menu = ctk.CTkOptionMenu(
            self.weekday_frame,
            variable=self.weekday_var,
            values=["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"],
        )
        self.weekday_menu.pack(fill="x", pady=5)

        time_row = ctk.CTkFrame(self.planer_left, fg_color="transparent")
        time_row.pack(fill="x", padx=20, pady=8)
        time_row.grid_columnconfigure(0, weight=1)
        time_row.grid_columnconfigure(1, weight=1)

        start_frame = ctk.CTkFrame(time_row, fg_color="transparent")
        start_frame.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkLabel(start_frame, text="Start (HH:MM)").pack(anchor="w")
        self.start_entry = ctk.CTkEntry(start_frame)
        self.start_entry.pack(fill="x", pady=5)
        self.start_entry.insert(0, "08:00")

        end_frame = ctk.CTkFrame(time_row, fg_color="transparent")
        end_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        ctk.CTkLabel(end_frame, text="Ende (HH:MM)").pack(anchor="w")
        self.end_entry = ctk.CTkEntry(end_frame)
        self.end_entry.pack(fill="x", pady=5)
        self.end_entry.insert(0, "18:00")

        ctk.CTkLabel(self.planer_left, text="Räume (Priorität 1-3)").pack(anchor="w", padx=20, pady=(10, 5))
        self.rooms_scroll = ctk.CTkScrollableFrame(self.planer_left, height=220)
        self.rooms_scroll.pack(fill="x", padx=20, pady=(0, 10))
        self.room_vars: Dict[str, ctk.BooleanVar] = {}
        self._render_rooms()

        self.add_queue_btn = ctk.CTkButton(
            self.planer_left,
            text="Zur Queue hinzufügen",
            command=self._add_job_to_queue,
        )
        self.add_queue_btn.pack(fill="x", padx=20, pady=(5, 20))

        ctk.CTkLabel(self.planer_right, text="Aktuelle Warteschlange", font=("", 16, "bold")).pack(
            anchor="w", padx=20, pady=(20, 10)
        )
        self.queue_info = ctk.CTkLabel(self.planer_right, text="Die Liste ist leer.")
        self.queue_info.pack(anchor="w", padx=20)
        self.queue_scroll = ctk.CTkScrollableFrame(self.planer_right, height=340)
        self.queue_scroll.pack(fill="both", expand=True, padx=20, pady=10)

        action_frame = ctk.CTkFrame(self.planer_right, fg_color="transparent")
        action_frame.pack(fill="x", padx=20, pady=(0, 20))
        self.blueprint_name_entry = ctk.CTkEntry(action_frame, placeholder_text="Blueprint Name")
        self.blueprint_name_entry.pack(fill="x", pady=5)
        ctk.CTkButton(action_frame, text="Als Blueprint speichern", command=self._save_blueprint).pack(
            fill="x", pady=5
        )
        ctk.CTkButton(action_frame, text="Liste leeren", command=self._clear_queue).pack(fill="x", pady=5)
        ctk.CTkButton(action_frame, text="Alle Jobs ausführen", command=self._run_queue).pack(
            fill="x", pady=5
        )

        self._toggle_date_mode()
        self._render_queue()

    def _build_blueprints_ui(self) -> None:
        frame = self.frames["blueprints"]
        ctk.CTkLabel(frame, text="Meine Blueprints", font=("", 20, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            frame,
            text="Hier findest du deine gespeicherten Vorlagen. Klicke auf Laden, um sie in die Queue zu kopieren.",
        ).pack(anchor="w", pady=(0, 10))

        self.blueprints_scroll = ctk.CTkScrollableFrame(frame, height=600)
        self.blueprints_scroll.pack(fill="both", expand=True)
        self._render_blueprints()

    def _build_accounts_ui(self) -> None:
        frame = self.frames["accounts"]
        ctk.CTkLabel(frame, text="Accounts & Einstellungen", font=("", 20, "bold")).pack(anchor="w")

        tabs = ctk.CTkTabview(frame)
        tabs.pack(fill="both", expand=True, pady=10)
        accounts_tab = tabs.add("Accounts")
        system_tab = tabs.add("System")

        ctk.CTkLabel(accounts_tab, text="Account Import", font=("", 14, "bold")).pack(anchor="w", pady=(10, 5))
        ctk.CTkLabel(accounts_tab, text="Format: email:passwort (eine Zeile pro Account)").pack(
            anchor="w"
        )
        self.import_text = ctk.CTkTextbox(accounts_tab, height=100)
        self.import_text.pack(fill="x", pady=8)
        ctk.CTkButton(accounts_tab, text="Importieren", command=self._import_accounts).pack(anchor="w")

        ctk.CTkLabel(accounts_tab, text="Account Übersicht", font=("", 14, "bold")).pack(
            anchor="w", pady=(15, 5)
        )
        self.accounts_scroll = ctk.CTkScrollableFrame(accounts_tab, height=320)
        self.accounts_scroll.pack(fill="both", expand=True, pady=(0, 10))

        ctk.CTkButton(accounts_tab, text="Account hinzufügen", command=self._add_account_row).pack(
            anchor="w", pady=(0, 10)
        )
        ctk.CTkButton(accounts_tab, text="Accounts speichern", command=self._save_accounts).pack(anchor="w")

        ctk.CTkLabel(system_tab, text="System Einstellungen", font=("", 14, "bold")).pack(
            anchor="w", pady=(10, 5)
        )
        self.sim_var = ctk.BooleanVar(value=self.settings.simulation)
        ctk.CTkCheckBox(system_tab, text="Simulations-Modus aktiv", variable=self.sim_var).pack(
            anchor="w", pady=5
        )
        self.debug_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(system_tab, text="Browser sichtbar (Debug)", variable=self.debug_var).pack(
            anchor="w", pady=5
        )
        ctk.CTkButton(system_tab, text="Räume neu scannen", command=self._run_scan, fg_color="#E59400").pack(
            anchor="w", pady=(5, 10)
        )
        
        # --- NEUER BUTTON FÜR RESERVATIONS EXPORT ---
        ctk.CTkButton(system_tab, text="Reservationen exportieren (CSV)", command=self._export_reservations, fg_color="#2B78E4").pack(
            anchor="w", pady=(5, 10)
        )

        ctk.CTkLabel(system_tab, text="Logs", font=("", 14, "bold")).pack(anchor="w", pady=(10, 5))
        self.log_text = ctk.CTkTextbox(system_tab, height=220)
        self.log_text.pack(fill="both", expand=True)
        ctk.CTkButton(system_tab, text="Logs speichern", command=self._save_logs).pack(anchor="w", pady=8)

        self._render_accounts()

    def _toggle_date_mode(self) -> None:
        mode = self.mode_var.get()
        if mode == "Einzel-Datum":
            self.weekday_frame.pack_forget()
            self.date_frame.pack(fill="x", padx=20, pady=8)
        else:
            self.date_frame.pack_forget()
            self.weekday_frame.pack(fill="x", padx=20, pady=8)

    def _render_rooms(self) -> None:
        for child in self.rooms_scroll.winfo_children():
            child.destroy()
        self.room_vars = {}
        if not self.rooms:
            ctk.CTkLabel(self.rooms_scroll, text="Bitte zuerst einen Raum-Scan durchführen.").pack()
            return
        for name in self.rooms:
            var = ctk.BooleanVar(value=False)
            checkbox = ctk.CTkCheckBox(self.rooms_scroll, text=name, variable=var)
            checkbox.pack(anchor="w", pady=2)
            self.room_vars[name] = var

    def _render_queue(self) -> None:
        for child in self.queue_scroll.winfo_children():
            child.destroy()
        if not self.jobs:
            self.queue_info.configure(text="Die Liste ist leer. Füge links Aufträge hinzu oder lade einen Blueprint.")
            return
        self.queue_info.configure(text="")
        for idx, job in enumerate(self.jobs):
            row = ctk.CTkFrame(self.queue_scroll)
            row.pack(fill="x", pady=4)
            label_text = f"{job.label} | {job.start_time} - {job.end_time}"
            ctk.CTkLabel(row, text=label_text).pack(side="left", padx=10)
            rooms_text = ", ".join(job.rooms)
            ctk.CTkLabel(row, text=rooms_text, text_color="gray").pack(side="left", padx=10)
            ctk.CTkButton(row, text="Entfernen", width=90, command=lambda i=idx: self._remove_job(i)).pack(
                side="right", padx=10
            )

    def _render_blueprints(self) -> None:
        for child in self.blueprints_scroll.winfo_children():
            child.destroy()
        if not self.blueprints:
            ctk.CTkLabel(self.blueprints_scroll, text="Noch keine Blueprints vorhanden.").pack(pady=20)
            return
        for name, jobs in self.blueprints.items():
            card = ctk.CTkFrame(self.blueprints_scroll)
            card.pack(fill="x", pady=8)
            ctk.CTkLabel(card, text=name, font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(card, text=f"{len(jobs)} Aufträge enthalten", text_color="gray").pack(
                anchor="w", padx=10
            )
            preview = "\n".join(
                [f"- {job.label} {job.start_time}-{job.end_time}" for job in jobs]
            )
            preview_box = ctk.CTkTextbox(card, height=80)
            preview_box.insert("1.0", preview)
            preview_box.configure(state="disabled")
            preview_box.pack(fill="x", padx=10, pady=6)
            ctk.CTkButton(card, text="Laden", command=lambda n=name: self._load_blueprint(n)).pack(
                anchor="e", padx=10, pady=(0, 8)
            )

    def _render_accounts(self) -> None:
        for child in self.accounts_scroll.winfo_children():
            child.destroy()
        self.account_widgets = []
        for idx, account in enumerate(self.settings.accounts):
            row = ctk.CTkFrame(self.accounts_scroll)
            row.pack(fill="x", pady=4)
            active_var = ctk.BooleanVar(value=account.active)
            active_cb = ctk.CTkCheckBox(row, text="Aktiv", variable=active_var)
            active_cb.pack(side="left", padx=5)
            email_entry = ctk.CTkEntry(row, placeholder_text="Email", width=220)
            email_entry.pack(side="left", padx=5)
            email_entry.insert(0, account.email)
            password_entry = ctk.CTkEntry(row, placeholder_text="Passwort", show="*", width=160)
            password_entry.pack(side="left", padx=5)
            password_entry.insert(0, account.password)
            status_label = ctk.CTkLabel(row, text=account.status)
            status_label.pack(side="left", padx=5)
            delete_btn = ctk.CTkButton(row, text="Löschen", width=80, command=lambda i=idx: self._delete_account(i))
            delete_btn.pack(side="right", padx=5)
            self.account_widgets.append((active_var, email_entry, password_entry, status_label))

    def _add_account_row(self) -> None:
        self.settings.accounts.append(Account())
        self._render_accounts()
        self._refresh_status()

    def _delete_account(self, idx: int) -> None:
        if idx < len(self.settings.accounts):
            del self.settings.accounts[idx]
        if not self.settings.accounts:
            self.settings.accounts.append(Account())
        self._render_accounts()
        self._refresh_status()

    def _import_accounts(self) -> None:
        text = self.import_text.get("1.0", "end").strip()
        if not text:
            self.logger.log("Keine Accounts zum Importieren.")
            return
        count = 0
        for line in text.splitlines():
            if ":" in line:
                email, password = line.split(":", 1)
                self.settings.accounts.append(Account(email=email.strip(), password=password.strip(), active=True))
                count += 1
        self.logger.log(f"{count} Accounts importiert.")
        self.import_text.delete("1.0", "end")
        self._render_accounts()
        self._refresh_status()

    def _save_accounts(self) -> None:
        updated_accounts = []
        for active_var, email_entry, password_entry, status_label in self.account_widgets:
            updated_accounts.append(
                Account(
                    email=email_entry.get().strip(),
                    password=password_entry.get().strip(),
                    active=active_var.get(),
                    status=status_label.cget("text"),
                )
            )
        self.settings.accounts = updated_accounts
        self.settings.simulation = self.sim_var.get()
        SettingsStore.save(self.settings)
        self.logger.log("Accounts gespeichert.")
        self._refresh_status()

    def _run_scan(self) -> None:
        self._save_accounts()
        active_accounts = [acc for acc in self.settings.accounts if acc.active and acc.email]
        if not active_accounts:
            self.logger.log("Kein aktiver Account für den Scan.")
            return
        self.worker.show_browser = self.debug_var.get()
        threading.Thread(target=lambda: self._perform_scan(active_accounts[0]), daemon=True).start()

    def _perform_scan(self, account: Account) -> None:
        res = self.worker.update_room_list(account.email, account.password)
        if res:
            self.rooms = res
            RoomStore.save(res)
            self.after(0, self._render_rooms)
            
    def _export_reservations(self) -> None:
        self._save_accounts()
        active_accounts = [acc for acc in self.settings.accounts if acc.active and acc.email]
        if not active_accounts:
            self.logger.log("Keine aktiven Accounts für den Export.")
            return
        
        self.logger.log(f"Starte Export für {len(active_accounts)} Accounts...")
        self.worker.show_browser = self.debug_var.get()
        threading.Thread(target=lambda: self.worker.fetch_reservations(active_accounts), daemon=True).start()

    def _add_job_to_queue(self) -> None:
        mode = self.mode_var.get()
        rooms = [name for name, var in self.room_vars.items() if var.get()]
        if not rooms:
            self.logger.log("Bitte mindestens einen Raum auswählen.")
            return
        start = self.start_entry.get().strip()
        end = self.end_entry.get().strip()
        if mode == "Einzel-Datum":
            date_str = self.date_entry.get().strip()
            try:
                selected_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            except ValueError:
                self.logger.log("Ungültiges Datum. Format: TT.MM.JJJJ")
                return
            today = date.today()
            if selected_date < today or selected_date > today + timedelta(days=14):
                self.logger.log("Datum muss innerhalb der nächsten 14 Tage liegen.")
                return
            job = Job("single", date_str, start, end, rooms)
        else:
            weekday = self.weekday_var.get()
            job = Job("relative", weekday, start, end, rooms)
        self.jobs.append(job)
        self.logger.log(f"Job hinzugefügt: {job.label}")
        self._render_queue()
        self._refresh_status()

    def _remove_job(self, idx: int) -> None:
        if idx < len(self.jobs):
            del self.jobs[idx]
        self._render_queue()
        self._refresh_status()

    def _clear_queue(self) -> None:
        self.jobs = []
        self._render_queue()
        self._refresh_status()

    def _save_blueprint(self) -> None:
        name = self.blueprint_name_entry.get().strip()
        if not name:
            self.logger.log("Bitte einen Blueprint-Namen angeben.")
            return
        if not self.jobs:
            self.logger.log("Keine Jobs in der Queue.")
            return
        self.blueprints[name] = list(self.jobs)
        BlueprintStore.save(self.blueprints)
        self.logger.log(f"Blueprint gespeichert: {name}")
        self.blueprint_name_entry.delete(0, "end")
        self._render_blueprints()

    def _load_blueprint(self, name: str) -> None:
        jobs = self.blueprints.get(name, [])
        self.jobs.extend(jobs)
        self.logger.log(f"Blueprint geladen: {name}")
        self._render_queue()
        self._refresh_status()

    def _run_queue(self) -> None:
        if not self.jobs:
            self.logger.log("Keine Jobs in der Queue.")
            return
        active_accounts = [acc for acc in self.settings.accounts if acc.active and acc.email]
        if not active_accounts:
            self.logger.log("Keine aktiven Accounts verfügbar.")
            return
        self.worker.show_browser = self.debug_var.get()
        self.settings.simulation = self.sim_var.get()
        SettingsStore.save(self.settings)
        threading.Thread(target=self._process_queue, args=(active_accounts,), daemon=True).start()

    def _process_queue(self, accounts: List[Account]) -> None:
        self.logger.log("--- START: QUEUE ---")
        for job in self.jobs:
            resolved_date = self._resolve_job_date(job)
            if not resolved_date:
                self.logger.log(f"Job übersprungen (ungültiges Datum): {job.label}")
                continue
            tasks = self._build_tasks(job, resolved_date)
            if not tasks:
                continue
            self.worker.execute_booking(tasks, accounts, job.rooms, self.settings.simulation)
        self.logger.log("--- ENDE: QUEUE ---")

    def _resolve_job_date(self, job: Job) -> Optional[str]:
        if job.date_mode == "single":
            return job.date_value
        weekday_map = {
            "Montag": 0,
            "Dienstag": 1,
            "Mittwoch": 2,
            "Donnerstag": 3,
            "Freitag": 4,
            "Samstag": 5,
        }
        target = weekday_map.get(job.date_value)
        if target is None:
            return None
        today = date.today()
        for offset in range(0, 14):
            candidate = today + timedelta(days=offset)
            if candidate.weekday() == target:
                return candidate.strftime("%d.%m.%Y")
        return None

    def _build_tasks(self, job: Job, resolved_date: str) -> List[Dict[str, object]]:
        tasks = []
        try:
            start, end, fmt = job.start_time, job.end_time, "%H:%M"
            tc, te = datetime.strptime(start, fmt), datetime.strptime(end, fmt)
            while tc < te:
                tn = tc + timedelta(hours=4)
                if tn > te:
                    tn = te
                tasks.append(
                    {
                        "start": tc.strftime(fmt),
                        "end": tn.strftime(fmt),
                        "date": resolved_date,
                        "all_rooms": self.rooms,
                    }
                )
                tc = tn
        except Exception as e:
            self.logger.log(f"Zeitformat Fehler: {e}")
            return []
        return tasks

    def _save_logs(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Textdatei", "*.txt")],
            title="Logs speichern",
        )
        if not path:
            return
        try:
            content = self.log_text.get("1.0", "end").strip()
            Path(path).write_text(content, encoding="utf-8")
            self.logger.log(f"Logs gespeichert: {path}")
        except Exception as e:
            self.logger.log(f"Fehler beim Speichern der Logs: {e}")

    def _refresh_status(self) -> None:
        active_count = len([acc for acc in self.settings.accounts if acc.email])
        self.status_accounts.configure(text=f"Accounts: {active_count}")
        self.status_jobs.configure(text=f"Jobs in Queue: {len(self.jobs)}")

    def _start_log_pump(self) -> None:
        while not self.log_queue.empty():
            message = self.log_queue.get()
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
        self.after(200, self._start_log_pump)

    def _ensure_playwright_ready(self) -> None:
        inst = PlaywrightInstaller(self.logger)
        if inst.is_installed():
            return

        popup = ctk.CTkToplevel(self)
        popup.title("Installation")
        popup.geometry("500x300")
        popup.grab_set()
        ctk.CTkLabel(popup, text="Lade Browser...", font=("", 14, "bold")).pack(pady=10)
        status_lbl = ctk.CTkLabel(popup, text="Starte...", wraplength=450, font=("Courier", 12))
        status_lbl.pack(pady=10)
        prog = ctk.CTkProgressBar(popup, mode="indeterminate")
        prog.pack(pady=10)
        prog.start()

        def update_status(text: str) -> None:
            self.after(0, lambda: status_lbl.configure(text=text[-100:]))

        def run_install() -> None:
            if inst.install(update_status):
                self.after(0, popup.destroy)

        threading.Thread(target=run_install, daemon=True).start()


if __name__ == "__main__":
    if "--install-browsers" in sys.argv:
        PlaywrightInstaller(Logger(queue.Queue(), LOG_FILE)).install()
    else:
        RoomBookerApp().mainloop()
