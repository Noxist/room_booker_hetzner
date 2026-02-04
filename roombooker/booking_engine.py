import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from playwright.sync_api import sync_playwright

from roombooker.config import APP_DIR, URLS
from roombooker.models import Account
from roombooker.utils import human_sleep


class BookingEngine:
    def __init__(self, logger) -> None:
        self.logger = logger

    def get_context(self, p, session_path: Optional[Path] = None):
        self.logger.log("Starte Browser (Headless)...")
        browser = p.chromium.launch(
            headless=True,
            slow_mo=50,
            args=["--start-maximized", "--window-size=1600,900"],
        )

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

    def perform_login(self, page, email: str, password: str) -> bool:
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
                except Exception as exc:
                    self.logger.log(f"Warnung Standortwahl (versuche Fortfahren): {exc}")

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
                except Exception as exc:
                    self.logger.log(f"Fehler bei Login-Trigger: {exc}")

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
                except Exception as exc:
                    self.logger.log(f"Fehler beim Ausfüllen des Logins: {exc}")
                    return False

            if page.locator("#navbarUser").is_visible() or "/event/add" in page.url:
                return True

            return False

        except Exception as exc:
            self.logger.log(f"Fehler in perform_login: {exc}")
            return False

    def execute_booking(
        self,
        tasks: List[Dict[str, object]],
        accounts: List[Account],
        preferred_rooms: List[str],
        simulation_mode: bool,
        summary: str = "Lernen",
    ) -> List[Dict[str, object]]:
        self.logger.log("--- START: INTERNE BUCHUNG ---")
        if simulation_mode:
            self.logger.log("SIMULATIONS-MODUS (keine Buchung)")

        successes: List[Dict[str, object]] = []
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
                session_file = APP_DIR / f"session_{acc.email.replace('@', '_')}.json"
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

                            page.fill("#event_title", summary)
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

                            if block_success:
                                date_value = datetime.strptime(task["date"], "%d.%m.%Y").date()
                                start_dt = datetime.combine(date_value, datetime.strptime(task["start"], "%H:%M").time())
                                end_dt = datetime.combine(date_value, datetime.strptime(task["end"], "%H:%M").time())
                                successes.append({"start": start_dt, "end": end_dt, "room": room_name})
                        finally:
                            browser.close()
                except Exception as exc:
                    self.logger.log(f"Fehler bei Buchungsvorgang: {exc}")

            if not block_success:
                self.logger.log(f"FEHLER: Block {task['start']} konnte nicht gebucht werden.")
            human_sleep(1)
        self.logger.log("--- PROZESS ENDE ---")
        return successes
