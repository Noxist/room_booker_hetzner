import json
import os
import queue
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
import tkinter as tk
from tkinter import messagebox

APP_NAME = "RoomBooker"
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
        return base / APP_NAME
    return Path.home() / ".config" / APP_NAME


APP_DIR = get_app_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = APP_DIR / "settings.json"
STORAGE_STATE_FILE = APP_DIR / "storage_state.json"
PLAYWRIGHT_BROWSERS_PATH = APP_DIR / "playwright"


@dataclass
class Account:
    email: str = ""
    password: str = ""


@dataclass
class Settings:
    accounts: List[Account] = field(default_factory=lambda: [Account() for _ in range(3)])
    rooms_priority: List[str] = field(default_factory=list)
    last_date: str = ""
    last_start: str = "08:00"
    last_end: str = "12:00"
    simulation: bool = True


def load_settings() -> Settings:
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
        rooms_priority=data.get("rooms_priority", []),
        last_date=data.get("last_date", ""),
        last_start=data.get("last_start", "08:00"),
        last_end=data.get("last_end", "12:00"),
        simulation=data.get("simulation", True),
    )


def save_settings(settings: Settings) -> None:
    data = {
        "accounts": [acc.__dict__ for acc in settings.accounts],
        "rooms_priority": settings.rooms_priority,
        "last_date": settings.last_date,
        "last_start": settings.last_start,
        "last_end": settings.last_end,
        "simulation": settings.simulation,
    }
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def ensure_playwright_browsers(ui_callback: Callable[[str], None], progress_callback: Callable[[bool], None]) -> None:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_PATH)
    PLAYWRIGHT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)

    if any(path.name.startswith("chromium") for path in PLAYWRIGHT_BROWSERS_PATH.glob("*") if path.is_dir()):
        return

    progress_callback(True)
    ui_callback("Playwright browsers missing. Installing Chromium...")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        if process.stdout:
            for line in process.stdout:
                ui_callback(line.strip())
        process.wait()
        if process.returncode != 0:
            ui_callback("Playwright installation failed. Please retry.")
        else:
            ui_callback("Playwright browsers installed.")
    except Exception as exc:
        ui_callback(f"Installation error: {exc}")
    finally:
        progress_callback(False)


class RoomBooker:
    def __init__(self, log_callback: Callable[[str], None]):
        self.log = log_callback

    def _get_context(self, playwright):
        browser = playwright.chromium.launch(headless=True)
        if STORAGE_STATE_FILE.exists():
            self.log("Using stored session.")
            context = browser.new_context(locale="de-CH", storage_state=str(STORAGE_STATE_FILE))
        else:
            self.log("Creating new session.")
            context = browser.new_context(locale="de-CH")
        return browser, context

    def _handle_auth(self, page, account: Account) -> None:
        if "login" in page.url or "wayf" in page.url or "eduid" in page.url:
            self.log("Authentication required.")
            page.set_default_timeout(0)
            page.set_default_navigation_timeout(0)
            try:
                page.wait_for_selector("input")
                user_field = "input[name='j_username'], #username"
                if page.is_visible(user_field):
                    page.fill(user_field, account.email)

                if page.is_visible("input[type='password']"):
                    page.fill("input[type='password']", account.password)
                    page.click("button[name='_eventId_proceed']", force=True)
                else:
                    page.keyboard.press("Enter")
                    time.sleep(2)
                    if page.is_visible("input[type='password']"):
                        page.fill("input[type='password']", account.password)
                        page.click("button[name='_eventId_proceed']", force=True)
                page.wait_for_url("**/event/**")
            except Exception as exc:
                self.log(f"Auth error: {exc}")

    def _ensure_location(self, page) -> None:
        if "/select" in page.url:
            try:
                page.click(f"main a[href*='{VONROLL_LOCATION_PATH}']", force=True)
                page.wait_for_url("**/event/**")
            except Exception:
                pass

        if "/event/add" not in page.url:
            page.goto(EVENT_ADD_URL)
            page.wait_for_load_state("domcontentloaded")

    def extract_rooms(self, page) -> Dict[str, str]:
        methods = [
            ("JS Selector #event_room", "() => Object.fromEntries(Array.from(document.querySelector('#event_room')?.options || []).filter(o => o.value).map(o => [o.innerText.trim(), o.value]))"),
            ("JS Generic Select", "() => { const s = Array.from(document.querySelectorAll('select')).find(x => x.options.length > 5); return s ? Object.fromEntries(Array.from(s.options).filter(o => o.value).map(o => [o.innerText.trim(), o.value])) : {}; }"),
            ("Playwright Locator", None),
            ("DOM Attribute Scan", "() => { const r = {}; document.querySelectorAll('option').forEach(o => { if(o.value && o.value.length < 5) r[o.innerText.trim()] = o.value; }); return r; }"),
            ("Hardcoded Database", None),
        ]

        for name, script in methods:
            try:
                if script:
                    result = page.evaluate(script)
                elif name == "Playwright Locator":
                    result = {}
                    for option in page.locator("#event_room option").all():
                        text = option.inner_text().strip()
                        value = option.get_attribute("value")
                        if value:
                            result[text] = value
                else:
                    result = HARDCODED_ROOMS

                if result and len(result) >= 2:
                    self.log(f"Room scan success with {name} ({len(result)} rooms).")
                    return result
                self.log(f"Room scan failed with {name}.")
            except Exception as exc:
                self.log(f"Room scan error ({name}): {exc}")
        return {}

    def run_scan(self, account: Account) -> Dict[str, str]:
        with sync_playwright() as playwright:
            browser, context = self._get_context(playwright)
            try:
                page = context.new_page()
                page.set_default_timeout(0)
                page.set_default_navigation_timeout(0)
                page.goto(EVENT_ADD_URL)
                self._handle_auth(page, account)
                self._ensure_location(page)
                rooms = self.extract_rooms(page)
                if rooms:
                    STORAGE_STATE_FILE.write_text(json.dumps(context.storage_state(), indent=2), encoding="utf-8")
                    return rooms
            except Exception as exc:
                self.log(f"Scan failed: {exc}")
            finally:
                browser.close()
        return {}

    def run_booking(
        self,
        date_str: str,
        start_time: str,
        end_time: str,
        rooms_priority: List[str],
        accounts: List[Account],
        simulation: bool,
    ) -> None:
        tasks = []
        fmt = "%H:%M"
        start_dt = datetime.strptime(start_time, fmt)
        end_dt = datetime.strptime(end_time, fmt)
        current = start_dt
        while current < end_dt:
            next_dt = min(current + timedelta(hours=4), end_dt)
            tasks.append({"start": current.strftime(fmt), "end": next_dt.strftime(fmt)})
            current = next_dt

        with sync_playwright() as playwright:
            browser, context = self._get_context(playwright)
            for idx, task in enumerate(tasks):
                account = accounts[idx % len(accounts)]
                self.log(f"Booking block {idx + 1}: {task['start']} - {task['end']}")
                try:
                    page = context.new_page()
                    page.set_default_timeout(0)
                    page.set_default_navigation_timeout(0)
                    page.goto(EVENT_ADD_URL)
                    self._handle_auth(page, account)
                    self._ensure_location(page)

                    room_map = self.extract_rooms(page)
                    success = False
                    for room_name in rooms_priority:
                        if room_name not in room_map:
                            continue
                        room_id = room_map[room_name]
                        self.log(f"Trying room: {room_name}")
                        page.goto(EVENT_ADD_URL)
                        page.select_option("#event_room", value=room_id)
                        page.fill("#event_startDate", f"{date_str} {task['start']}")
                        page.keyboard.press("Enter")
                        duration = int(
                            (datetime.strptime(task["end"], fmt) - datetime.strptime(task["start"], fmt)).total_seconds()
                            / 60
                        )
                        page.evaluate(
                            "document.getElementById('event_duration').value = arguments[0];"
                            "document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}));",
                            duration,
                        )
                        page.fill("#event_title", "Study")

                        if simulation:
                            self.log("Simulation mode enabled - skipping submit.")
                            success = True
                            break

                        page.click("#event_submit")
                        try:
                            page.wait_for_url("**/event**")
                            if "/add" not in page.url:
                                self.log(f"Booking success: {room_name}")
                                success = True
                                break
                        except Exception:
                            pass

                    if not success:
                        self.log("No rooms available for this block.")

                    STORAGE_STATE_FILE.write_text(json.dumps(context.storage_state(), indent=2), encoding="utf-8")
                    page.close()
                except Exception as exc:
                    self.log(f"Booking error: {exc}")
            browser.close()


class RoomBookerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("Room Booker")
        self.geometry("900x650")
        self.resizable(False, False)

        self.settings = load_settings()
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.progress_active = tk.BooleanVar(value=False)

        self._build_ui()
        self._start_log_pump()
        self._ensure_playwright_ready()

    def _build_ui(self):
        header = ctk.CTkLabel(self, text="Room Booker", font=ctk.CTkFont(size=26, weight="bold"))
        header.pack(pady=12)

        self.tabview = ctk.CTkTabview(self, width=860, height=540)
        self.tabview.pack(pady=10)

        self.booking_tab = self.tabview.add("Booking")
        self.settings_tab = self.tabview.add("Settings")

        self._build_booking_tab()
        self._build_settings_tab()

        self.progress_frame = ctk.CTkFrame(self, fg_color=("#1f1f1f", "#1f1f1f"))
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="")
        self.progress_label.pack(pady=(20, 10))
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, mode="indeterminate", width=400)
        self.progress_bar.pack(pady=(0, 20))

    def _build_booking_tab(self):
        form_frame = ctk.CTkFrame(self.booking_tab)
        form_frame.pack(padx=20, pady=20, fill="x")

        date_label = ctk.CTkLabel(form_frame, text="Date (DD.MM.YYYY)")
        date_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.date_entry = ctk.CTkEntry(form_frame, width=180)
        self.date_entry.grid(row=0, column=1, padx=10, pady=10)
        default_date = self.settings.last_date or (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
        self.date_entry.insert(0, default_date)

        start_label = ctk.CTkLabel(form_frame, text="Start")
        start_label.grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.start_entry = ctk.CTkEntry(form_frame, width=180)
        self.start_entry.grid(row=1, column=1, padx=10, pady=10)
        self.start_entry.insert(0, self.settings.last_start)

        end_label = ctk.CTkLabel(form_frame, text="End")
        end_label.grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.end_entry = ctk.CTkEntry(form_frame, width=180)
        self.end_entry.grid(row=2, column=1, padx=10, pady=10)
        self.end_entry.insert(0, self.settings.last_end)

        rooms_label = ctk.CTkLabel(form_frame, text="Rooms (priority order)")
        rooms_label.grid(row=0, column=2, padx=10, pady=10, sticky="w")
        self.rooms_listbox = tk.Listbox(form_frame, height=6, width=30)
        self.rooms_listbox.grid(row=1, column=2, rowspan=3, padx=10, pady=10)
        self._refresh_rooms_listbox()

        rooms_buttons = ctk.CTkFrame(form_frame, fg_color="transparent")
        rooms_buttons.grid(row=1, column=3, rowspan=3, padx=10, pady=10)
        ctk.CTkButton(rooms_buttons, text="Move Up", command=self._move_room_up, width=110).pack(pady=4)
        ctk.CTkButton(rooms_buttons, text="Move Down", command=self._move_room_down, width=110).pack(pady=4)
        ctk.CTkButton(rooms_buttons, text="Remove", command=self._remove_room, width=110).pack(pady=4)

        self.simulation_var = tk.BooleanVar(value=self.settings.simulation)
        simulation_toggle = ctk.CTkCheckBox(form_frame, text="Simulation mode", variable=self.simulation_var)
        simulation_toggle.grid(row=3, column=0, padx=10, pady=10, sticky="w")

        start_button = ctk.CTkButton(self.booking_tab, text="Start Booking", command=self._start_booking)
        start_button.pack(pady=10)

        self.log_text = tk.Text(self.booking_tab, height=12, width=100, state="disabled", bg="#1e1e1e", fg="#f5f5f5")
        self.log_text.pack(padx=20, pady=10)

    def _build_settings_tab(self):
        settings_frame = ctk.CTkFrame(self.settings_tab)
        settings_frame.pack(padx=20, pady=20, fill="both", expand=True)

        accounts_label = ctk.CTkLabel(settings_frame, text="Accounts (max 3)", font=ctk.CTkFont(weight="bold"))
        accounts_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 5))

        self.account_entries: List[Dict[str, ctk.CTkEntry]] = []
        for idx in range(3):
            email_entry = ctk.CTkEntry(settings_frame, width=260, placeholder_text="Email")
            password_entry = ctk.CTkEntry(settings_frame, width=260, show="*", placeholder_text="Password")
            email_entry.grid(row=idx + 1, column=0, padx=10, pady=5, sticky="w")
            password_entry.grid(row=idx + 1, column=1, padx=10, pady=5, sticky="w")
            email_entry.insert(0, self.settings.accounts[idx].email)
            password_entry.insert(0, self.settings.accounts[idx].password)
            self.account_entries.append({"email": email_entry, "password": password_entry})

        rooms_section = ctk.CTkFrame(settings_frame, fg_color="transparent")
        rooms_section.grid(row=1, column=2, rowspan=4, padx=20, pady=5, sticky="n")

        rooms_label = ctk.CTkLabel(rooms_section, text="Room Management", font=ctk.CTkFont(weight="bold"))
        rooms_label.pack(anchor="w", pady=(0, 8))

        self.new_room_entry = ctk.CTkEntry(rooms_section, width=220, placeholder_text="Room name")
        self.new_room_entry.pack(pady=5)
        ctk.CTkButton(rooms_section, text="Add Room", command=self._add_room).pack(pady=5, fill="x")
        ctk.CTkButton(rooms_section, text="Refresh Rooms", command=self._refresh_rooms).pack(pady=5, fill="x")

        save_button = ctk.CTkButton(settings_frame, text="Save Settings", command=self._save_settings)
        save_button.grid(row=5, column=0, columnspan=2, padx=10, pady=20, sticky="w")

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")

    def _start_log_pump(self):
        def pump():
            while not self.log_queue.empty():
                msg = self.log_queue.get()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
            self.after(250, pump)

        pump()

    def _toggle_progress(self, active: bool) -> None:
        if active:
            self.progress_frame.place(relx=0.5, rely=0.5, anchor="center")
            self.progress_label.configure(text="Installing Playwright Browsers")
            self.progress_bar.start()
        else:
            self.progress_bar.stop()
            self.progress_frame.place_forget()

    def _ensure_playwright_ready(self):
        def run_install():
            ensure_playwright_browsers(self._log, self._toggle_progress)

        thread = threading.Thread(target=run_install, daemon=True)
        thread.start()

    def _refresh_rooms_listbox(self) -> None:
        self.rooms_listbox.delete(0, tk.END)
        for room in self.settings.rooms_priority:
            self.rooms_listbox.insert(tk.END, room)

    def _add_room(self):
        room = self.new_room_entry.get().strip()
        if not room:
            return
        if room not in self.settings.rooms_priority:
            self.settings.rooms_priority.append(room)
        self.new_room_entry.delete(0, tk.END)
        self._refresh_rooms_listbox()

    def _remove_room(self):
        selection = self.rooms_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        self.settings.rooms_priority.pop(idx)
        self._refresh_rooms_listbox()

    def _move_room_up(self):
        selection = self.rooms_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        if idx == 0:
            return
        self.settings.rooms_priority[idx - 1], self.settings.rooms_priority[idx] = (
            self.settings.rooms_priority[idx],
            self.settings.rooms_priority[idx - 1],
        )
        self._refresh_rooms_listbox()
        self.rooms_listbox.selection_set(idx - 1)

    def _move_room_down(self):
        selection = self.rooms_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        if idx == len(self.settings.rooms_priority) - 1:
            return
        self.settings.rooms_priority[idx + 1], self.settings.rooms_priority[idx] = (
            self.settings.rooms_priority[idx],
            self.settings.rooms_priority[idx + 1],
        )
        self._refresh_rooms_listbox()
        self.rooms_listbox.selection_set(idx + 1)

    def _save_settings(self):
        accounts = []
        for entries in self.account_entries:
            email = entries["email"].get().strip()
            password = entries["password"].get().strip()
            accounts.append(Account(email=email, password=password))
        self.settings.accounts = accounts
        save_settings(self.settings)
        messagebox.showinfo("Saved", "Settings saved successfully.")

    def _refresh_rooms(self):
        self._save_settings()
        accounts = [acc for acc in self.settings.accounts if acc.email and acc.password]
        if not accounts:
            messagebox.showerror("Missing Account", "Please enter at least one account to scan rooms.")
            return

        def run_scan():
            self._log("Starting room scan...")
            rooms = RoomBooker(self._log).run_scan(accounts[0])
            if rooms:
                self.settings.rooms_priority = list(rooms.keys())
                self._refresh_rooms_listbox()
                save_settings(self.settings)
                self._log("Room scan completed.")
            else:
                self._log("Room scan failed.")

        threading.Thread(target=run_scan, daemon=True).start()

    def _start_booking(self):
        self._save_settings()
        rooms = self.settings.rooms_priority
        accounts = [acc for acc in self.settings.accounts if acc.email and acc.password]
        if not rooms:
            messagebox.showerror("Missing Rooms", "Please add or scan rooms before booking.")
            return
        if not accounts:
            messagebox.showerror("Missing Account", "Please enter at least one account.")
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
            messagebox.showerror("Invalid Input", "Please check date and time formats.")
            return

        self.settings.last_date = date_str
        self.settings.last_start = start_time
        self.settings.last_end = end_time
        self.settings.simulation = simulation
        save_settings(self.settings)

        def run_booking():
            self._log("Booking started...")
            RoomBooker(self._log).run_booking(date_str, start_time, end_time, rooms, accounts, simulation)
            self._log("Booking finished.")

        threading.Thread(target=run_booking, daemon=True).start()


if __name__ == "__main__":
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_PATH))
    app = RoomBookerApp()
    app.mainloop()
