import csv
import importlib.util
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from playwright.sync_api import sync_playwright

from roombooker.config import APP_DIR, CSV_EXPORT_FILE, LOGIC_OVERRIDE_FILE, URLS
from roombooker.models import Account
from roombooker.utils import human_sleep, human_type


class BookingWorker:
    def __init__(self, logger):
        self.logger = logger
        # Diese Variable wird von der GUI (gui.py) über die Checkbox gesteuert
        self.show_browser = False 
        self._no_override = object()

    def get_context(self, p, session_path: Optional[Path] = None, *, force_visible: bool = False):
        # Logik: Wenn force_visible True ist, dann sichtbar.
        # Ansonsten entscheidet die User-Einstellung (self.show_browser).
        is_headless = False if force_visible else not self.show_browser

        self.logger.log(f"Starte Browser (Sichtbar: {not is_headless})...")
        
        try:
            # Wir erzwingen hier ein grosses Fenster
            browser = p.chromium.launch(
                headless=is_headless, 
                slow_mo=50,
                args=["--start-maximized", "--window-size=1600,900"]
            )
        except Exception as e:
            self.logger.log(f"Fehler Browser-Start: {e}")
            raise e

        args = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1600, "height": 900},
            "locale": "de-CH",
        }
        
        if session_path and session_path.exists():
            self.logger.log(f"Lade Session: {session_path.name}")
            args["storage_state"] = str(session_path)

        context = browser.new_context(**args)
        page = context.new_page()
        return browser, context, page

    def _load_override_module(self):
        if not LOGIC_OVERRIDE_FILE.exists():
            return None
        try:
            module_name = f"roombooker_logic_override_{int(time.time() * 1000)}"
            spec = importlib.util.spec_from_file_location(module_name, LOGIC_OVERRIDE_FILE)
            if spec is None or spec.loader is None:
                self.logger.log("Override-Datei gefunden, aber nicht ladbar.")
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            self.logger.log(f"Fehler beim Laden des Overrides: {e}")
            return None

    def _run_override(self, function_name: str, *args, **kwargs):
        if not LOGIC_OVERRIDE_FILE.exists():
            return self._no_override
        module = self._load_override_module()
        if not module:
            return self._no_override
        override_fn = getattr(module, function_name, None)
        if not callable(override_fn):
            return self._no_override
        self.logger.log(f"Hot-Swap Override aktiv: {function_name}")
        return override_fn(self, *args, **kwargs)

    def perform_login(self, page, email, password) -> bool:
        override = self._run_override("perform_login", page, email, password)
        if override is not self._no_override:
            return override
        try:
            if "/event/add" not in page.url:
                self.logger.log(f"Navigiere zu {URLS['event_add']}...")
                page.goto(URLS["event_add"])
                page.wait_for_load_state("domcontentloaded")

            if "/select" in page.url:
                self.logger.log("Standortwahl erkannt...")
                try:
                    if page.locator("#navbarDropDownRight").is_visible():
                        page.click("#navbarDropDownRight")
                        human_sleep(0.5)
                    elif page.locator(".navbar-toggler").is_visible():
                        self.logger.log("Mobiles Menü erkannt, öffne Navigation...")
                        page.click(".navbar-toggler")
                        human_sleep(0.5)
                        if page.locator("#navbarDropDownRight").is_visible():
                            page.click("#navbarDropDownRight")
                            human_sleep(0.5)

                    self.logger.log("Wähle Bibliothek vonRoll...")
                    page.click(f"a[href*='{URLS['vonroll_location_path']}']")
                    page.wait_for_load_state("networkidle")
                except Exception as e:
                    self.logger.log(f"Warnung Standortwahl (versuche Fortfahren): {e}")

            human_sleep(1)

            if "login" not in page.url and "wayf" not in page.url and "eduid" not in page.url:
                if page.locator("#navbarUser").is_visible():
                    return True
                self.logger.log("Suche Login-Trigger...")
                try:
                    trigger = page.locator(".timeline-cell-clickable").first
                    if trigger.count() > 0:
                        trigger.click()
                    else:
                        self.logger.log("Keine Zellen gefunden, klicke blind...")
                        page.mouse.click(800, 450)
                    time.sleep(3)
                except Exception as e:
                    self.logger.log(f"Fehler bei Login-Trigger: {e}")

            if page.locator("#username").is_visible() or "eduid" in page.url:
                self.logger.log(f"Führe Login durch für {email}...")
                try:
                    page.wait_for_selector("#username", timeout=5000)
                    page.fill("#username", email)
                    human_sleep(0.5)
                    if page.locator("button[name='_eventId_submit']").is_visible():
                        page.click("button[name='_eventId_submit']")
                    else:
                        page.keyboard.press("Enter")
                    human_sleep(1.5)
                    page.wait_for_selector("#password", timeout=5000)
                    page.fill("#password", password)
                    human_sleep(0.5)
                    if page.locator("button[name='_eventId_proceed']").is_visible():
                        page.click("button[name='_eventId_proceed']")
                    else:
                        page.keyboard.press("Enter")
                    self.logger.log("Login abgeschickt. Warte auf Session...")
                    page.wait_for_load_state("networkidle")
                    time.sleep(8)
                except Exception as e:
                    self.logger.log(f"Fehler beim Ausfüllen des Logins: {e}")
                    return False

            if page.locator("#navbarUser").is_visible() or "/event/add" in page.url:
                return True
            return False
        except Exception as e:
            self.logger.log(f"Fehler in perform_login: {e}")
            return False

    def update_room_list(self, email: str, password: str) -> Optional[Dict[str, str]]:
        override = self._run_override("update_room_list", email, password)
        if override is not self._no_override:
            return override
        try:
            with sync_playwright() as p:
                # FIX HIER: force_visible nicht hardcoden!
                browser, _, page = self.get_context(p, force_visible=self.show_browser)
                try:
                    self.logger.log("Starte Raum-Scan...")
                    if self.perform_login(page, email, password):
                        self.logger.log("Login OK. Scanne Räume...")
                        if "/event/add" not in page.url:
                            page.goto(URLS["event_add"])
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
        override = self._run_override("fetch_reservations", accounts)
        if override is not self._no_override:
            return override
        all_reservations = []

        with sync_playwright() as p:
            for acc in accounts:
                if not acc.active or not acc.email:
                    continue
                self.logger.log(f"Hole Reservationen für: {acc.email}")
                # FIX HIER EBENFALLS
                browser, context, page = self.get_context(p, force_visible=self.show_browser)

                try:
                    if self.perform_login(page, acc.email, acc.password):
                        self.logger.log(f"Gehe zu {URLS['reservations']}...")
                        page.goto(URLS["reservations"])
                        page.wait_for_load_state("networkidle")
                        human_sleep(2)
                        if page.locator("table.table").is_visible():
                            rows = page.locator("table.table tbody tr").all()
                            count = 0
                            if len(rows) > 0:
                                for row in rows:
                                    cells = row.locator("td").all()
                                    if len(cells) >= 4:
                                        raw_time = " ".join(cells[0].inner_text().split())
                                        title = cells[1].inner_text().strip()
                                        location = cells[2].inner_text().strip()
                                        room = cells[3].inner_text().strip()
                                        all_reservations.append(
                                            {
                                                "Account": acc.email,
                                                "Zeit": raw_time,
                                                "Titel": title,
                                                "Ort": location,
                                                "Raum": room,
                                                "Abgerufen_am": datetime.now().strftime("%d.%m.%Y %H:%M"),
                                            }
                                        )
                                        count += 1
                                self.logger.log(f"-> {count} Reservationen gefunden.")
                            else:
                                self.logger.log("-> Keine Reservationen in der Liste.")
                        else:
                            self.logger.log("-> Keine Tabelle gefunden (Login evtl. unvollständig?).")
                    else:
                        self.logger.log(f"-> Login fehlgeschlagen für {acc.email}")
                except Exception as e:
                    self.logger.log(f"Fehler beim Abruf: {e}")
                finally:
                    browser.close()

        if all_reservations:
            try:
                keys = all_reservations[0].keys()
                with open(CSV_EXPORT_FILE, "w", newline="", encoding="utf-8") as handle:
                    dict_writer = csv.DictWriter(handle, fieldnames=keys)
                    dict_writer.writeheader()
                    dict_writer.writerows(all_reservations)
                self.logger.log(f"ERFOLG: Alle Reservationen gespeichert in: {CSV_EXPORT_FILE}")
            except Exception as e:
                self.logger.log(f"Fehler beim Speichern der CSV: {e}")
        else:
            self.logger.log("Keine Reservationen zum Speichern gefunden.")

    def execute_booking(self, tasks, accounts, preferred_rooms, simulation_mode) -> None:
        override = self._run_override("execute_booking", tasks, accounts, preferred_rooms, simulation_mode)
        if override is not self._no_override:
            return override
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
                            if not self.perform_login(page, acc.email, acc.password):
                                self.logger.log("Login fehlgeschlagen.")
                                continue
                            context.storage_state(path=str(session_file))
                            if "/event/add" not in page.url:
                                page.goto(URLS["event_add"])
                                page.wait_for_load_state("domcontentloaded")

                            # Raum setzen
                            page.evaluate(
                                "v => { var s=document.getElementById('event_room'); "
                                "s.value=v; s.dispatchEvent(new Event('change')); }",
                                room_id,
                            )
                            human_sleep(0.5)
                            
                            page.fill("#event_startDate", f"{task['date']} {task['start']}")
                            page.keyboard.press("Enter")
                            human_sleep(0.5)

                            t1 = datetime.strptime(task["start"], "%H:%M")
                            t2 = datetime.strptime(task["end"], "%H:%M")
                            dur = int((t2 - t1).total_seconds() / 60)

                            page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
                            page.evaluate(
                                "document.getElementById('event_duration').dispatchEvent("
                                "new Event('change', {bubbles: true}))"
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
                                    page.wait_for_url(lambda u: "/event/add" not in u, timeout=5000)
                                    self.logger.log(f"ERFOLG: {room_name} gebucht!")
                                    block_success = True
                                except Exception:
                                    content = page.content().lower()
                                    if "konflikt" in content or "belegt" in content:
                                        self.logger.log(f"Raum {room_name} ist belegt.")
                                    else:
                                        if "/event/add" in page.url:
                                            self.logger.log(f"Fehler bei {room_name} (Keine Bestätigung).")
                                        else:
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
