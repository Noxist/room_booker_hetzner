import queue
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import customtkinter as ctk
from tkinter import filedialog

from roombooker.browser import BookingWorker
from roombooker.config import APP_NAME, HARDCODED_ROOMS, LOG_FILE, get_version
from roombooker.installer import PlaywrightInstaller
from roombooker.models import Account, Job
from roombooker.storage import BlueprintStore, RoomStore, SettingsStore
from roombooker.utils import Logger


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

        ctk.CTkButton(
            system_tab,
            text="Reservationen exportieren (CSV)",
            command=self._export_reservations,
            fg_color="#2B78E4",
        ).pack(anchor="w", pady=(5, 10))

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
            preview = "\n".join([f"- {job.label} {job.start_time}-{job.end_time}" for job in jobs])
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

        def _scan_wrapper() -> None:
            try:
                self._perform_scan(active_accounts[0])
            except Exception as e:
                self.logger.log(f"Scan fehlgeschlagen: {e}")

        threading.Thread(target=_scan_wrapper, daemon=True).start()

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

        def _export_wrapper() -> None:
            try:
                self.worker.fetch_reservations(active_accounts)
            except Exception as e:
                self.logger.log(f"Export fehlgeschlagen: {e}")

        threading.Thread(target=_export_wrapper, daemon=True).start()

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

        def _queue_wrapper() -> None:
            try:
                self._process_queue(active_accounts)
            except Exception as e:
                self.logger.log(f"Queue-Fehler: {e}")

        threading.Thread(target=_queue_wrapper, daemon=True).start()

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
