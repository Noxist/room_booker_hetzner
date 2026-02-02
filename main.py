import json
import os
import queue
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import customtkinter as ctk
from playwright.sync_api import sync_playwright

# --- KONFIGURATION ---
APP_NAME = "Room Booker Ultimate"
VERSION = "3.1 (Smart Logic)"
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
DEBUG_DIR = APP_DIR / "debug_screenshots"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
INSTALL_LOCK_TTL_SECONDS = 60 * 60

def get_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

INSTALL_DIR = get_install_dir()
LOG_DIR = INSTALL_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "room_booker.log"


# --- HELPER FUNKTIONEN ---

def human_type(page, selector: str, text: str) -> None:
    try:
        page.focus(selector)
        for char in text:
            page.keyboard.type(char, delay=random.randint(20, 60))
    except Exception:
        return

def human_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


# --- KLASSEN ---

class OutputRedirector:
    """Fängt Konsolenausgaben ab und sendet sie an eine Callback-Funktion fürs GUI."""
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
        return Settings(
            accounts=accounts[:3],
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


# --- NEUE LOGIK (Vom zweiten Skript übernommen) ---

class BookingWorker:
    def __init__(self, logger: Logger):
        self.logger = logger

    def get_context(self, p, session_path: Optional[Path] = None):
        # HEADLESS auf True gesetzt, damit keine Fenster aufpoppen (wie gewünscht)
        browser = p.chromium.launch(headless=True, slow_mo=50) 
        args = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "viewport": {"width": 1300, "height": 900},
            "locale": "de-CH",
        }
        if session_path and session_path.exists():
            self.logger.log(f"DEBUG: Lade Cookie aus {session_path.name}")
            args["storage_state"] = str(session_path)
        
        context = browser.new_context(**args)
        page = context.new_page()
        return browser, context, page

    def navigate_to_target(self, page, email, password) -> bool:
        max_retries = 20
        self.logger.log("Navigiere zum Formular...")
        
        for i in range(max_retries):
            try:
                url = page.url
                
                # Ziel erreicht?
                if "/event/add" in url and "login" not in url:
                    return True

                # Standortwahl (/select)
                if "/select" in url:
                    self.logger.log("Standortwahl erkannt.")
                    try:
                        loc_selector = f"main a[href*='{VONROLL_LOCATION_PATH}']"
                        if page.locator(loc_selector).count() > 0:
                            page.click(loc_selector)
                        else:
                            page.locator("main ul li a").first.click()
                        
                        # Sofort weiter zum Ziel erzwingen
                        page.goto(EVENT_ADD_URL)
                        continue 
                    except: pass

                # Login
                elif "eduid.ch" in url or "login" in url or "wayf" in url:
                    self.logger.log(f"Login Maske erkannt.")
                    try:
                        try: page.wait_for_selector("input", timeout=2000)
                        except: pass

                        sel_user = "input[name='j_username'], #username, #userId"
                        sel_pass = "input[type='password'], #password"
                        sel_btn  = "button[name='_eventId_proceed']"

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
                        
                        elif page.is_visible(sel_user):
                            page.keyboard.press("Enter")
                            page.wait_for_timeout(1500)
                            continue
                    except: pass

                else:
                    # Unbekannt, versuche Navigation
                    page.goto(EVENT_ADD_URL)
                    page.wait_for_timeout(2000)

            except:
                page.wait_for_timeout(1000)
        
        return False

    def update_room_list(self, email, password) -> Optional[Dict[str, str]]:
        self.logger.log("--- START: RAUM SCAN ---")
        with sync_playwright() as p:
            browser, context, page = self.get_context(p)
            try:
                page.goto(EVENT_ADD_URL)
                if self.navigate_to_target(page, email, password):
                    self.logger.log("Extrahiere Raumliste (JS Direct)...")
                    page.wait_for_load_state("domcontentloaded")
                    human_sleep(1)
                    
                    # Strategie: JS Direct (Aus neuem Code übernommen)
                    js_data = page.evaluate("""() => {
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
                    }""")
                    
                    if js_data:
                        self.logger.log(f"Scan erfolgreich: {len(js_data)} Räume.")
                        return js_data
                    else:
                        self.logger.log("Keine Räume gefunden (Element leer?)")
                        return None
                else:
                    self.logger.log("Scan Abbruch: Ziel nicht erreicht.")
                    return None
            except Exception as e:
                self.logger.log(f"Fehler Scan: {e}")
                return None
            finally:
                browser.close()

    def refresh_session(self, idx, email, password) -> None:
        self.logger.log(f"--- SESSION {idx+1} CHECK ---")
        session_file = APP_DIR / f"session_{idx}.json"
        with sync_playwright() as p:
            browser, context, page = self.get_context(p)
            try:
                page.goto(EVENT_ADD_URL)
                if self.navigate_to_target(page, email, password):
                    context.storage_state(path=str(session_file))
                    self.logger.log(f"Session {idx+1} OK.")
                else:
                    self.logger.log("Session Check fehlgeschlagen.")
            finally:
                browser.close()

    def execute_booking(self, tasks, accounts, preferred_rooms, simulation_mode) -> None:
        self.logger.log("--- START: SMART BUCHUNG ---")
        if simulation_mode:
            self.logger.log("ACHTUNG: Simulations-Modus AN. Es wird NICHT gespeichert.")
        
        acc_idx = 0

        for i, task in enumerate(tasks):
            block_success = False
            
            # Wir versuchen jeden Raum in der Liste
            for room_name in preferred_rooms:
                if block_success: break # Block erledigt

                room_id = task['all_rooms'].get(room_name)
                if not room_id: continue

                acc = accounts[acc_idx % len(accounts)]
                session_file = APP_DIR / f"session_{acc_idx % len(accounts)}.json"
                acc_idx += 1

                self.logger.log(f"Versuche: {task['start']}-{task['end']} in '{room_name}'...")
                
                with sync_playwright() as p:
                    browser, context, page = self.get_context(p, session_path=session_file)
                    try:
                        page.goto(EVENT_ADD_URL)
                        
                        if not self.navigate_to_target(page, acc.email, acc.password):
                            self.logger.log("Login fehlgeschlagen, versuche nächsten...")
                            continue

                        # Session updaten
                        context.storage_state(path=str(session_file))

                        # --- FORMULAR (Aus neuer Logik) ---
                        # 1. Raum setzen (JS Force)
                        page.evaluate(f"v => {{ var s=document.getElementById('event_room'); s.value=v; s.dispatchEvent(new Event('change')); }}", room_id)
                        human_sleep(0.5)

                        # 2. Datum/Zeit
                        full_start = f"{task['date']} {task['start']}"
                        page.fill("#event_startDate", full_start)
                        page.keyboard.press("Enter")
                        human_sleep(0.8)

                        # 3. Dauer
                        fmt = "%H:%M"
                        t1 = datetime.strptime(task['start'], fmt)
                        t2 = datetime.strptime(task['end'], fmt)
                        dur = int((t2 - t1).total_seconds() / 60)
                        
                        page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
                        page.evaluate("document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))")
                        human_sleep(0.5)

                        # 4. Titel
                        human_type(page, "#event_title", "Lernen")
                        if page.is_visible('input[name="event[purpose]"][value="Other"]'):
                            page.check('input[name="event[purpose]"][value="Other"]')

                        # 5. Speichern / Check
                        if simulation_mode:
                            self.logger.log("SIMULATION: Wäre erfolgreich (Button nicht gedrückt).")
                            block_success = True
                            # Screenshot simulation
                            try: page.screenshot(path=DEBUG_DIR / f"sim_success_{i}.png")
                            except: pass
                        else:
                            self.logger.log("Drücke Speichern...")
                            page.click("#event_submit") # Der echte Klick
                            
                            # Wir warten 5 Sekunden.
                            try:
                                page.wait_for_url("**/event**", timeout=5000)
                                if "/add" not in page.url:
                                    self.logger.log(f"ERFOLG! Raum {room_name} gebucht.")
                                    block_success = True
                                else:
                                    self.logger.log(f"Warnung: URL hat sich nicht geändert.")
                                    raise Exception("URL unverändert")
                            except:
                                self.logger.log(f"Raum {room_name} scheint belegt/fehlerhaft. Versuche nächsten...")
                                try: page.screenshot(path=DEBUG_DIR / f"fail_{room_name}_{i}.png")
                                except: pass
                    
                    except Exception as e:
                        self.logger.log(f"Fehler bei Versuch: {e}")
                    finally:
                        try: browser.close()
                        except: pass
            
            if not block_success:
                self.logger.log(f"FEHLER: Kein freier Raum gefunden für {task['start']}-{task['end']}!")
            
            human_sleep(2)

        self.logger.log("--- PROZESS ENDE ---")


# --- INSTALLER (Beibehalten) ---

class PlaywrightInstaller:
    def __init__(self, logger: Logger):
        self.logger = logger
        self._install_lock = threading.Lock()

    def is_installed(self) -> bool:
        if not PLAYWRIGHT_BROWSERS_PATH.exists(): return False
        return any(path.name.startswith("chromium") for path in PLAYWRIGHT_BROWSERS_PATH.iterdir() if path.is_dir())

    def install(self, output_callback: Optional[Callable[[str], None]] = None) -> bool:
        if self._install_lock.locked(): return False
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
                if output_callback: output_callback(str(e))
                return False
            finally:
                sys.stdout, sys.stderr = orig_stdout, orig_stderr
                sys.argv = old_argv
        finally:
            self._install_lock.release()

# --- GUI (Beibehalten) ---

class RoomBookerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("1200x820")
        self.log_queue = queue.Queue()
        self.logger = Logger(self.log_queue, LOG_FILE)
        self.worker = BookingWorker(self.logger)
        self.settings = SettingsStore.load()
        self.rooms = RoomStore.load() or HARDCODED_ROOMS
        ctk.set_appearance_mode(self.settings.theme)
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_frames()
        self._show_frame("dashboard")
        self._start_log_pump()
        self.after(500, self._ensure_playwright_ready)

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(self.sidebar, text="Room Booker", font=("", 22, "bold")).pack(pady=20)
        for name, f in [("Dashboard", "dashboard"), ("Accounts", "accounts"), ("Einstellungen", "settings"), ("Logs", "logs")]:
            ctk.CTkButton(self.sidebar, text=name, command=lambda nm=f: self._show_frame(nm)).pack(fill="x", padx=20, pady=5)
        ctk.CTkButton(self.sidebar, text="Beenden", fg_color="#8b1f1f", command=self.destroy).pack(side="bottom", fill="x", padx=20, pady=20)

    def _build_frames(self):
        self.frames = {n: ctk.CTkFrame(self, corner_radius=0, fg_color="transparent") for n in ["dashboard", "accounts", "settings", "logs"]}
        for f in self.frames.values(): f.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self._build_dashboard_ui()
        self._build_accounts_ui()
        self._build_settings_ui()
        self._build_logs_ui()

    def _show_frame(self, name):
        for n, f in self.frames.items(): f.tkraise() if n == name else None

    def _build_dashboard_ui(self):
        f = self.frames["dashboard"]
        
        # Datum und Zeit Inputs
        time_frame = ctk.CTkFrame(f)
        time_frame.pack(fill="x", pady=10)
        
        ctk.CTkLabel(time_frame, text="Datum:").pack(side="left", padx=10)
        self.date_entry = ctk.CTkEntry(time_frame, width=100, placeholder_text="DD.MM.YYYY")
        self.date_entry.pack(side="left", padx=5)
        self.date_entry.insert(0, (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y"))
        
        ctk.CTkLabel(time_frame, text="Start:").pack(side="left", padx=10)
        self.start_entry = ctk.CTkEntry(time_frame, width=60)
        self.start_entry.pack(side="left", padx=5)
        self.start_entry.insert(0, "08:00")
        
        ctk.CTkLabel(time_frame, text="Ende:").pack(side="left", padx=10)
        self.end_entry = ctk.CTkEntry(time_frame, width=60)
        self.end_entry.pack(side="left", padx=5)
        self.end_entry.insert(0, "18:00")
        
        # Raumliste
        self.rooms_scroll = ctk.CTkScrollableFrame(f, height=300, label_text="Bevorzugte Räume")
        self.rooms_scroll.pack(fill="x", pady=10)
        self.room_vars = {}
        self._render_rooms()
        
        # Controls
        self.sim_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(f, text="Simulations-Modus (Nicht buchen)", variable=self.sim_var).pack(pady=10)
        self.start_btn = ctk.CTkButton(f, text="Buchung starten", fg_color="#1f8a4c", command=self._start_booking, height=40)
        self.start_btn.pack(pady=10, fill="x")

    def _render_rooms(self):
        for w in self.rooms_scroll.winfo_children(): w.destroy()
        if not self.rooms:
            ctk.CTkLabel(self.rooms_scroll, text="Bitte erst Scan in Einstellungen durchführen!").pack()
        for name in self.rooms:
            v = ctk.BooleanVar(value=name in self.settings.selected_rooms)
            ctk.CTkCheckBox(self.rooms_scroll, text=name, variable=v).pack(anchor="w", pady=2)
            self.room_vars[name] = v

    def _build_accounts_ui(self):
        f = self.frames["accounts"]
        ctk.CTkLabel(f, text="Accounts verwalten", font=("", 16, "bold")).pack(pady=10)
        self.acc_entries = []
        for i in range(3):
            row = ctk.CTkFrame(f); row.pack(fill="x", pady=5)
            ctk.CTkLabel(row, text=f"Account {i+1}").pack(side="left", padx=10)
            e = ctk.CTkEntry(row, placeholder_text="Email", width=200); e.pack(side="left", padx=5)
            e.insert(0, self.settings.accounts[i].email)
            p = ctk.CTkEntry(row, placeholder_text="Passwort", show="*", width=150); p.pack(side="left", padx=5)
            p.insert(0, self.settings.accounts[i].password)
            self.acc_entries.append((e, p))
            ctk.CTkButton(row, text="Test", width=50, command=lambda idx=i: self._test_acc(idx)).pack(side="right", padx=10)
            
        ctk.CTkButton(f, text="Speichern", command=self._save_accs).pack(pady=20)

    def _test_acc(self, idx):
        self._save_accs()
        acc = self.settings.accounts[idx]
        threading.Thread(target=lambda: self.worker.refresh_session(idx, acc.email, acc.password), daemon=True).start()

    def _save_accs(self):
        self.settings.accounts = [Account(e.get(), p.get()) for e, p in self.acc_entries]
        SettingsStore.save(self.settings)
        self.logger.log("Accounts gespeichert.")

    def _build_settings_ui(self):
        f = self.frames["settings"]
        ctk.CTkLabel(f, text="Datenbank", font=("", 16, "bold")).pack(pady=10)
        ctk.CTkButton(f, text="Räume neu scannen (aktualisieren)", command=self._run_scan, fg_color="#E59400").pack(pady=10, fill="x")
        ctk.CTkLabel(f, text="Hinweis: Für den Scan wird Account 1 verwendet.", text_color="gray").pack()

    def _run_scan(self):
        self._save_accs()
        threading.Thread(target=lambda: self._perform_scan(), daemon=True).start()
    
    def _perform_scan(self):
        acc = self.settings.accounts[0]
        if not acc.email:
            self.logger.log("Fehler: Account 1 hat keine Email.")
            return
        res = self.worker.update_room_list(acc.email, acc.password)
        if res:
            self.rooms = res
            RoomStore.save(res)
            self.after(0, self._render_rooms)

    def _build_logs_ui(self):
        self.log_text = ctk.CTkTextbox(self.frames["logs"], height=500)
        self.log_text.pack(fill="both", expand=True)

    def _start_log_pump(self):
        while not self.log_queue.empty():
            m = self.log_queue.get()
            self.log_text.insert("end", m + "\n")
            self.log_text.see("end")
        self.after(200, self._start_log_pump)

    def _start_booking(self):
        rooms = [n for n, v in self.room_vars.items() if v.get()]
        accs = [a for a in self.settings.accounts if a.email]
        
        # 4H Blöcke generieren
        tasks = []
        try:
            start_str = self.start_entry.get()
            end_str = self.end_entry.get()
            fmt = "%H:%M"
            t_curr = datetime.strptime(start_str, fmt)
            t_end = datetime.strptime(end_str, fmt)
            
            while t_curr < t_end:
                t_next = t_curr + timedelta(hours=4)
                if t_next > t_end: t_next = t_end
                tasks.append({
                    "start": t_curr.strftime(fmt), 
                    "end": t_next.strftime(fmt), 
                    "date": self.date_entry.get(), 
                    "all_rooms": self.rooms
                })
                t_curr = t_next
        except Exception as e:
            self.logger.log(f"Fehler bei Zeitformat: {e}")
            return

        if not rooms:
            self.logger.log("Bitte Räume auswählen.")
            return

        threading.Thread(target=lambda: self.worker.execute_booking(tasks, accs, rooms, self.sim_var.get()), daemon=True).start()

    def _ensure_playwright_ready(self):
        inst = PlaywrightInstaller(self.logger)
        if inst.is_installed(): return
        
        popup = ctk.CTkToplevel(self)
        popup.title("Installation")
        popup.geometry("500x300")
        popup.grab_set()
        ctk.CTkLabel(popup, text="Lade Browser-Komponenten...", font=("", 14, "bold")).pack(pady=10)
        ctk.CTkLabel(popup, text="Bitte warten, das Fenster schliesst sich automatisch.", text_color="gray").pack()
        status_lbl = ctk.CTkLabel(popup, text="Initialisiere...", wraplength=450, font=("Courier", 12))
        status_lbl.pack(pady=10)
        
        prog = ctk.CTkProgressBar(popup, mode="indeterminate")
        prog.pack(pady=10)
        prog.start()
        
        def update_st(t): self.after(0, lambda: status_lbl.configure(text=t[-100:]))
        def run():
            if inst.install(update_st): self.after(0, popup.destroy)
        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    if "--install-browsers" in sys.argv:
        PlaywrightInstaller(Logger(queue.Queue(), LOG_FILE)).install()
    else:
        RoomBookerApp().mainloop()
