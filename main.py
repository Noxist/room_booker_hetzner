import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import customtkinter as ctk
from playwright.sync_api import sync_playwright

APP_NAME = "Room Booker Ultimate"
VERSION = "2.8"
ROOM_BASE_URL = "https://raumreservation.ub.unibe.ch"
EVENT_ADD_URL = f"{ROOM_BASE_URL}/event/add"
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
SETTINGS_FILE = APP_DIR / "settings.json"
ROOMS_FILE = APP_DIR / "rooms.json"
PLAYWRIGHT_BROWSERS_PATH = APP_DIR / "playwright"
INSTALL_LOCK_FILE = APP_DIR / "playwright_install.lock"
INSTALL_LOCK_TTL_SECONDS = 60 * 60


def get_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


INSTALL_DIR = get_install_dir()
LOG_DIR = INSTALL_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "room_booker.log"


@dataclass
class Account:
    email: str = ""
    password: str = ""


@dataclass
class Settings:
    accounts: List[Account] = field(default_factory=lambda: [Account() for _ in range(3)])
    selected_rooms: List[str] = field(default_factory=list)
    last_date: str = ""
    last_start: str = "08:00"
    last_end: str = "18:00"
    simulation: bool = True
    theme: str = "Dark"


class SettingsStore:
    @staticmethod
    def load() -> Settings:
        if not SETTINGS_FILE.exists():
            return Settings()
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return Settings()

        accounts = [Account(**acc) for acc in data.get("accounts", [])]
        while len(accounts) < 3:
            accounts.append(Account())
        accounts = accounts[:3]

        return Settings(
            accounts=accounts,
            selected_rooms=data.get("selected_rooms", []),
            last_date=data.get("last_date", ""),
            last_start=data.get("last_start", "08:00"),
            last_end=data.get("last_end", "18:00"),
            simulation=data.get("simulation", True),
            theme=data.get("theme", "Dark"),
        )

    @staticmethod
    def save(settings: Settings) -> None:
        data = {
            "accounts": [acc.__dict__ for acc in settings.accounts],
            "selected_rooms": settings.selected_rooms,
            "last_date": settings.last_date,
            "last_start": settings.last_start,
            "last_end": settings.last_end,
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
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def save(room_map: Dict[str, str]) -> None:
        ROOMS_FILE.write_text(json.dumps(room_map, indent=2), encoding="utf-8")


class Logger:
    def __init__(self, queue_obj: "queue.Queue[str]", log_file: Path) -> None:
        self.queue = queue_obj
        self.log_file = log_file

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_msg = f"[{timestamp}] {message}"
        print(full_msg)
        try:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(full_msg + "\n")
        except Exception:
            pass
        self.queue.put(full_msg)


def human_type(page, selector: str, text: str) -> None:
    try:
        page.focus(selector)
        for char in text:
            page.keyboard.type(char, delay=random.randint(20, 60))
    except Exception:
        return


def human_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


class BookingWorker:
    def __init__(self, logger: Logger):
        self.logger = logger

    def get_context(self, playwright, session_path: Optional[Path] = None):
        browser = playwright.chromium.launch(headless=True)
        args = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1300, "height": 900},
            "locale": "de-CH",
        }
        if session_path and session_path.exists():
            self.logger.log(f"Session geladen: {session_path.name}")
            args["storage_state"] = str(session_path)
        context = browser.new_context(**args)
        page = context.new_page()
        return browser, context, page

    def navigate_to_target(self, page, email: str, password: str) -> bool:
        max_retries = 20
        self.logger.log("Navigiere zum Formular...")

        for _ in range(max_retries):
            try:
                url = page.url
                if "/event/add" in url and "login" not in url:
                    return True

                if "/select" in url:
                    self.logger.log("Standortwahl erkannt.")
                    try:
                        loc_selector = f"main a[href*='{VONROLL_LOCATION_PATH}']"
                        if page.locator(loc_selector).count() > 0:
                            page.click(loc_selector)
                        else:
                            page.locator("main ul li a").first.click()
                        page.goto(EVENT_ADD_URL)
                        continue
                    except Exception:
                        pass
                elif "eduid.ch" in url or "login" in url or "wayf" in url:
                    self.logger.log("Login Maske erkannt.")
                    try:
                        try:
                            page.wait_for_selector("input", timeout=2000)
                        except Exception:
                            pass

                        sel_user = "input[name='j_username'], #username, #userId"
                        sel_pass = "input[type='password'], #password"
                        sel_btn = "button[name='_eventId_proceed']"

                        if page.is_visible(sel_user) and not page.input_value(sel_user):
                            page.fill(sel_user, email)
                            human_sleep(0.2)

                        if page.is_visible(sel_pass):
                            page.fill(sel_pass, password)
                            human_sleep(0.3)
                            if page.locator(sel_btn).count() > 0:
                                page.locator(sel_btn).first.click(force=True)
                            else:
                                page.keyboard.press("Enter")
                            page.wait_for_timeout(4000)
                            continue

                        if page.is_visible(sel_user):
                            page.keyboard.press("Enter")
                            page.wait_for_timeout(1500)
                            continue
                    except Exception:
                        pass
                else:
                    page.goto(EVENT_ADD_URL)
                    page.wait_for_timeout(2000)
            except Exception:
                page.wait_for_timeout(1000)
        return False

    def update_room_list(self, email: str, password: str) -> Optional[Dict[str, str]]:
        self.logger.log("--- START: RAUM SCAN ---")
        with sync_playwright() as playwright:
            browser, context, page = self.get_context(playwright)
            try:
                page.goto(EVENT_ADD_URL)
                if self.navigate_to_target(page, email, password):
                    self.logger.log("Extrahiere Raumliste (JS)...")
                    page.wait_for_load_state("domcontentloaded")
                    human_sleep(1)

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

                    if js_data:
                        self.logger.log(f"Scan erfolgreich: {len(js_data)} Räume.")
                        return js_data

                    self.logger.log("Keine Räume gefunden (Element leer?).")
                    return None

                self.logger.log("Scan Abbruch: Ziel nicht erreicht.")
                return None
            except Exception as exc:
                self.logger.log(f"Fehler Scan: {exc}")
                return None
            finally:
                browser.close()

    def refresh_session(self, idx: int, email: str, password: str) -> None:
        self.logger.log(f"--- SESSION {idx + 1} CHECK ---")
        session_file = APP_DIR / f"session_{idx}.json"
        with sync_playwright() as playwright:
            browser, context, page = self.get_context(playwright)
            try:
                page.goto(EVENT_ADD_URL)
                if self.navigate_to_target(page, email, password):
                    context.storage_state(path=str(session_file))
                    self.logger.log(f"Session {idx + 1} OK.")
                else:
                    self.logger.log("Session Check fehlgeschlagen.")
            finally:
                browser.close()

    def execute_booking(
        self,
        tasks: List[Dict[str, str]],
        accounts: List[Account],
        preferred_rooms: List[str],
        simulation_mode: bool,
    ) -> None:
        self.logger.log("--- START: SMART BUCHUNG ---")
        if simulation_mode:
            self.logger.log("ACHTUNG: Simulations-Modus AN. Es wird NICHT gespeichert.")

        acc_idx = 0
        for i, task in enumerate(tasks):
            block_success = False
            for room_name in preferred_rooms:
                if block_success:
                    break

                room_id = task["all_rooms"].get(room_name)
                if not room_id:
                    continue

                acc = accounts[acc_idx % len(accounts)]
                session_file = APP_DIR / f"session_{acc_idx % len(accounts)}.json"
                acc_idx += 1

                self.logger.log(f"Versuche: {task['start']}-{task['end']} in '{room_name}'...")
                with sync_playwright() as playwright:
                    browser, context, page = self.get_context(playwright, session_path=session_file)
                    try:
                        page.goto(EVENT_ADD_URL)
                        if not self.navigate_to_target(page, acc.email, acc.password):
                            self.logger.log("Login fehlgeschlagen, versuche nächsten...")
                            continue

                        context.storage_state(path=str(session_file))

                        page.evaluate(
                            "v => { var s=document.getElementById('event_room'); s.value=v; "
                            "s.dispatchEvent(new Event('change')); }",
                            room_id,
                        )
                        human_sleep(0.5)

                        full_start = f"{task['date']} {task['start']}"
                        page.fill("#event_startDate", full_start)
                        page.keyboard.press("Enter")
                        human_sleep(0.8)

                        fmt = "%H:%M"
                        t1 = datetime.strptime(task["start"], fmt)
                        t2 = datetime.strptime(task["end"], fmt)
                        dur = int((t2 - t1).total_seconds() / 60)

                        page.evaluate("document.getElementById('event_duration').value = arguments[0]", dur)
                        page.evaluate(
                            "document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))"
                        )
                        human_sleep(0.5)

                        human_type(page, "#event_title", "Lernen")
                        if page.is_visible('input[name="event[purpose]"][value="Other"]'):
                            page.check('input[name="event[purpose]"][value="Other"]')

                        if simulation_mode:
                            self.logger.log("SIMULATION: Wäre erfolgreich (Button nicht gedrückt).")
                            block_success = True
                        else:
                            self.logger.log("Drücke Speichern...")
                            page.click("#event_submit")
                            try:
                                page.wait_for_url("**/event**", timeout=5000)
                                if "/add" not in page.url:
                                    self.logger.log(f"ERFOLG! Raum {room_name} gebucht.")
                                    block_success = True
                                else:
                                    self.logger.log("Warnung: URL hat sich nicht geändert.")
                                    raise RuntimeError("URL unverändert")
                            except Exception:
                                self.logger.log(f"Raum {room_name} scheint belegt/fehlerhaft. Versuche nächsten...")
                    except Exception as exc:
                        self.logger.log(f"Fehler bei Versuch: {exc}")
                    finally:
                        try:
                            browser.close()
                        except Exception:
                            pass

            if not block_success:
                self.logger.log(f"FEHLER: Kein freier Raum gefunden für {task['start']}-{task['end']}!")

            human_sleep(2)

        self.logger.log("--- PROZESS ENDE ---")


class PlaywrightInstaller:
    def __init__(self, logger: Logger):
        self.logger = logger
        self._install_lock = threading.Lock()

    def is_installed(self) -> bool:
        if not PLAYWRIGHT_BROWSERS_PATH.exists():
            return False
        return any(path.name.startswith("chromium") for path in PLAYWRIGHT_BROWSERS_PATH.iterdir() if path.is_dir())

    def _acquire_install_lock(self) -> bool:
        if self._install_lock.locked():
            return False
        if INSTALL_LOCK_FILE.exists():
            try:
                age = time.time() - INSTALL_LOCK_FILE.stat().st_mtime
                if age > INSTALL_LOCK_TTL_SECONDS:
                    INSTALL_LOCK_FILE.unlink()
                else:
                    return False
            except Exception:
                return False
        try:
            INSTALL_LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            return False
        self._install_lock.acquire()
        return True

    def _release_install_lock(self) -> None:
        if self._install_lock.locked():
            self._install_lock.release()
        try:
            if INSTALL_LOCK_FILE.exists():
                INSTALL_LOCK_FILE.unlink()
        except Exception:
            pass

    def install(self) -> bool:
        if not self._acquire_install_lock():
            return False
        PLAYWRIGHT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_PATH)
        self.logger.log("Playwright Browser werden installiert...")
        process = subprocess.Popen(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        if process.stdout:
            for line in process.stdout:
                self.logger.log(line.strip())
        process.wait()
        success = process.returncode == 0
        if success:
            self.logger.log("Playwright Installation abgeschlossen.")
        else:
            self.logger.log("Playwright Installation fehlgeschlagen.")
        self._release_install_lock()
        return success

    def wait_for_existing_install(self) -> None:
        while INSTALL_LOCK_FILE.exists():
            time.sleep(1)


class RoomBookerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("1200x820")
        self.minsize(1100, 760)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.logger = Logger(self.log_queue, LOG_FILE)
        self.worker = BookingWorker(self.logger)
        self.settings = SettingsStore.load()
        self.rooms = RoomStore.load() or HARDCODED_ROOMS

        ctk.set_appearance_mode(self.settings.theme)
        ctk.set_default_color_theme("dark-blue")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_frames()
        self._show_frame("dashboard")

        self._start_log_pump()
        self._install_in_progress = False
        self._ensure_playwright_ready()

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(self.sidebar, text="Room Booker", font=ctk.CTkFont(size=22, weight="bold")).pack(
            pady=(20, 10)
        )

        ctk.CTkButton(self.sidebar, text="Dashboard", command=lambda: self._show_frame("dashboard")).pack(
            fill="x", padx=20, pady=6
        )
        ctk.CTkButton(self.sidebar, text="Accounts", command=lambda: self._show_frame("accounts")).pack(
            fill="x", padx=20, pady=6
        )
        ctk.CTkButton(self.sidebar, text="Einstellungen", command=lambda: self._show_frame("settings")).pack(
            fill="x", padx=20, pady=6
        )
        ctk.CTkButton(self.sidebar, text="Logs", command=lambda: self._show_frame("logs")).pack(
            fill="x", padx=20, pady=6
        )

        self.theme_switch = ctk.CTkSwitch(
            self.sidebar,
            text="Dark Mode",
            command=self._toggle_theme,
        )
        self.theme_switch.pack(pady=20)
        self.theme_switch.select() if self.settings.theme == "Dark" else self.theme_switch.deselect()

        ctk.CTkButton(self.sidebar, text="Beenden", command=self.destroy, fg_color="#8b1f1f").pack(
            side="bottom", fill="x", padx=20, pady=20
        )

    def _build_frames(self) -> None:
        self.frames: Dict[str, ctk.CTkFrame] = {}

        self.frames["dashboard"] = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["accounts"] = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["settings"] = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["logs"] = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")

        for frame in self.frames.values():
            frame.grid(row=0, column=1, sticky="nsew", padx=24, pady=24)

        self._build_dashboard()
        self._build_accounts()
        self._build_settings()
        self._build_logs()

    def _show_frame(self, name: str) -> None:
        for key, frame in self.frames.items():
            if key == name:
                frame.tkraise()

    def _build_dashboard(self) -> None:
        frame = self.frames["dashboard"]
        frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(frame, text="Dashboard", font=ctk.CTkFont(size=20, weight="bold"))
        header.pack(anchor="w", pady=(0, 10))

        form_frame = ctk.CTkFrame(frame)
        form_frame.pack(fill="x", pady=10)

        date_label = ctk.CTkLabel(form_frame, text="Datum")
        date_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.date_entry = ctk.CTkEntry(form_frame, width=140)
        self.date_entry.grid(row=0, column=1, padx=10, pady=10)
        default_date = self.settings.last_date or (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
        self.date_entry.insert(0, default_date)

        start_label = ctk.CTkLabel(form_frame, text="Start")
        start_label.grid(row=0, column=2, padx=10, pady=10, sticky="w")
        self.start_entry = ctk.CTkEntry(form_frame, width=80)
        self.start_entry.grid(row=0, column=3, padx=10, pady=10)
        self.start_entry.insert(0, self.settings.last_start)

        end_label = ctk.CTkLabel(form_frame, text="Ende")
        end_label.grid(row=0, column=4, padx=10, pady=10, sticky="w")
        self.end_entry = ctk.CTkEntry(form_frame, width=80)
        self.end_entry.grid(row=0, column=5, padx=10, pady=10)
        self.end_entry.insert(0, self.settings.last_end)

        rooms_label = ctk.CTkLabel(frame, text="Bevorzugte Räume", font=ctk.CTkFont(size=16, weight="bold"))
        rooms_label.pack(anchor="w", pady=(16, 8))

        self.rooms_scroll = ctk.CTkScrollableFrame(frame, height=220)
        self.rooms_scroll.pack(fill="x", pady=6)

        self.room_vars: Dict[str, ctk.CTkCheckBox] = {}
        self._render_room_checkboxes()

        controls = ctk.CTkFrame(frame, fg_color="transparent")
        controls.pack(fill="x", pady=16)

        self.simulation_var = ctk.BooleanVar(value=self.settings.simulation)
        self.simulation_check = ctk.CTkCheckBox(controls, text="Simulations-Modus", variable=self.simulation_var)
        self.simulation_check.pack(side="left", padx=10)

        self.start_button = ctk.CTkButton(
            controls,
            text="Buchung starten",
            fg_color="#1f8a4c",
            height=45,
            command=self._start_booking,
        )
        self.start_button.pack(side="right", fill="x", expand=True, padx=10)

        self.progress_bar = ctk.CTkProgressBar(frame, mode="indeterminate")
        self.progress_bar.pack(fill="x", pady=8)
        self.progress_bar.stop()

    def _build_accounts(self) -> None:
        frame = self.frames["accounts"]
        header = ctk.CTkLabel(frame, text="Accounts", font=ctk.CTkFont(size=20, weight="bold"))
        header.pack(anchor="w", pady=(0, 10))

        self.account_entries: List[Dict[str, ctk.CTkEntry]] = []
        for idx in range(3):
            row = ctk.CTkFrame(frame)
            row.pack(fill="x", pady=6)

            label = ctk.CTkLabel(row, text=f"Account {idx + 1}")
            label.pack(side="left", padx=10)

            email_entry = ctk.CTkEntry(row, width=280, placeholder_text="E-Mail")
            email_entry.pack(side="left", padx=8)
            email_entry.insert(0, self.settings.accounts[idx].email)

            password_entry = ctk.CTkEntry(row, width=200, show="*", placeholder_text="Passwort")
            password_entry.pack(side="left", padx=8)
            password_entry.insert(0, self.settings.accounts[idx].password)

            test_button = ctk.CTkButton(
                row,
                text="Session testen",
                width=140,
                command=lambda i=idx: self._run_session_check(i),
            )
            test_button.pack(side="right", padx=10)

            self.account_entries.append({"email": email_entry, "password": password_entry})

        save_button = ctk.CTkButton(frame, text="Accounts speichern", command=self._save_accounts)
        save_button.pack(anchor="w", padx=10, pady=16)

    def _build_settings(self) -> None:
        frame = self.frames["settings"]
        header = ctk.CTkLabel(frame, text="Einstellungen", font=ctk.CTkFont(size=20, weight="bold"))
        header.pack(anchor="w", pady=(0, 10))

        room_frame = ctk.CTkFrame(frame)
        room_frame.pack(fill="x", pady=10)

        ctk.CTkLabel(room_frame, text="Räume", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=6)
        ctk.CTkButton(room_frame, text="Räume neu scannen", command=self._run_scan).pack(
            anchor="w", padx=10, pady=10
        )

        info_label = ctk.CTkLabel(
            frame,
            text="Hinweis: Einstellungen werden im Benutzerprofil gespeichert (Update-sicher).",
            text_color=("#c5c5c5", "#c5c5c5"),
        )
        info_label.pack(anchor="w", padx=10, pady=20)

    def _build_logs(self) -> None:
        frame = self.frames["logs"]
        header = ctk.CTkLabel(frame, text="Logs", font=ctk.CTkFont(size=20, weight="bold"))
        header.pack(anchor="w", pady=(0, 10))

        self.log_text = ctk.CTkTextbox(frame, height=520)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

    def _render_room_checkboxes(self) -> None:
        for widget in self.rooms_scroll.winfo_children():
            widget.destroy()

        self.room_vars.clear()
        if not self.rooms:
            ctk.CTkLabel(self.rooms_scroll, text="Keine Räume vorhanden.").pack(anchor="w")
            return

        for name in self.rooms.keys():
            var = ctk.BooleanVar(value=name in self.settings.selected_rooms)
            chk = ctk.CTkCheckBox(self.rooms_scroll, text=name, variable=var)
            chk.pack(anchor="w", pady=2, padx=6)
            self.room_vars[name] = chk

    def _start_log_pump(self) -> None:
        def pump():
            while not self.log_queue.empty():
                msg = self.log_queue.get()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
            self.after(200, pump)

        pump()

    def _toggle_theme(self) -> None:
        theme = "Dark" if self.theme_switch.get() == 1 else "Light"
        ctk.set_appearance_mode(theme)
        self.settings.theme = theme
        SettingsStore.save(self.settings)

    def _save_accounts(self) -> None:
        accounts = []
        for entries in self.account_entries:
            email = entries["email"].get().strip()
            password = entries["password"].get().strip()
            accounts.append(Account(email=email, password=password))
        self.settings.accounts = accounts
        SettingsStore.save(self.settings)
        self.logger.log("Accounts gespeichert.")

    def _run_session_check(self, idx: int) -> None:
        self._save_accounts()
        account = self.settings.accounts[idx]
        if not account.email:
            self.logger.log("Bitte zuerst E-Mail für diesen Account eintragen.")
            return

        threading.Thread(
            target=self.worker.refresh_session,
            args=(idx, account.email, account.password),
            daemon=True,
        ).start()

    def _run_scan(self) -> None:
        self._save_accounts()
        primary = self.settings.accounts[0]
        if not primary.email:
            self.logger.log("Für den Scan wird Account 1 benötigt.")
            return

        def scan():
            rooms = self.worker.update_room_list(primary.email, primary.password)
            if rooms:
                self.rooms = rooms
                RoomStore.save(self.rooms)
                self._render_room_checkboxes()
                self.logger.log("Räume aktualisiert.")
            else:
                self.logger.log("Raum-Scan fehlgeschlagen.")

        threading.Thread(target=scan, daemon=True).start()

    def _start_booking(self) -> None:
        selected_rooms = [name for name, chk in self.room_vars.items() if chk.get()]
        if not selected_rooms:
            self.logger.log("Bitte mindestens einen Raum auswählen.")
            return

        accounts = [acc for acc in self.settings.accounts if acc.email]
        if not accounts:
            self.logger.log("Keine Accounts hinterlegt.")
            return

        date_str = self.date_entry.get().strip()
        start_time = self.start_entry.get().strip()
        end_time = self.end_entry.get().strip()
        simulation = self.simulation_var.get()

        try:
            datetime.strptime(date_str, "%d.%m.%Y")
            datetime.strptime(start_time, "%H:%M")
            datetime.strptime(end_time, "%H:%M")
        except ValueError:
            self.logger.log("Bitte Datum/Zeit prüfen (Format DD.MM.YYYY und HH:MM).")
            return

        tasks = []
        fmt = "%H:%M"
        t_curr = datetime.strptime(start_time, fmt)
        t_end = datetime.strptime(end_time, fmt)
        while t_curr < t_end:
            t_next = min(t_curr + timedelta(hours=4), t_end)
            tasks.append(
                {
                    "start": t_curr.strftime(fmt),
                    "end": t_next.strftime(fmt),
                    "date": date_str,
                    "all_rooms": self.rooms,
                }
            )
            t_curr = t_next

        self.settings.selected_rooms = selected_rooms
        self.settings.last_date = date_str
        self.settings.last_start = start_time
        self.settings.last_end = end_time
        self.settings.simulation = simulation
        SettingsStore.save(self.settings)

        def run():
            self._set_booking_state(True)
            self.worker.execute_booking(tasks, accounts, selected_rooms, simulation)
            self._set_booking_state(False)

        threading.Thread(target=run, daemon=True).start()

    def _set_booking_state(self, active: bool) -> None:
        if active:
            self.progress_bar.start()
            self.start_button.configure(state="disabled")
        else:
            self.progress_bar.stop()
            self.start_button.configure(state="normal")

    def _ensure_playwright_ready(self) -> None:
        installer = PlaywrightInstaller(self.logger)
        if installer.is_installed():
            return
        if self._install_in_progress:
            return
        self._install_in_progress = True

        popup = ctk.CTkToplevel(self)
        popup.title("Playwright Setup")
        popup.geometry("420x160")
        popup.transient(self)
        popup.grab_set()

        label = ctk.CTkLabel(popup, text="Installiere Browser...", font=ctk.CTkFont(size=14))
        label.pack(pady=20)

        progress = ctk.CTkProgressBar(popup, mode="indeterminate", width=320)
        progress.pack(pady=10)
        progress.start()

        def finish_popup():
            progress.stop()
            popup.destroy()
            self._install_in_progress = False

        def run_install():
            if installer.install():
                self.after(0, finish_popup)
                return
            self.logger.log("Playwright Installation läuft bereits. Bitte warten...")
            installer.wait_for_existing_install()
            if installer.is_installed():
                self.logger.log("Playwright Installation abgeschlossen.")
            self.after(0, finish_popup)

        threading.Thread(target=run_install, daemon=True).start()


def run_install_only() -> int:
    logger = Logger(queue.Queue(), LOG_FILE)
    installer = PlaywrightInstaller(logger)
    if installer.is_installed():
        logger.log("Playwright ist bereits installiert.")
        return 0
    if not installer.install():
        logger.log("Playwright Installation läuft bereits. Bitte warten...")
        installer.wait_for_existing_install()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_PATH))
    if "--install-browsers" in sys.argv:
        raise SystemExit(run_install_only())
    app = RoomBookerApp()
    app.mainloop()
