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
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "viewport": {"width": 1600, "height": 900},
            "locale": "de-CH",
        }
        if session_path and session_path.exists():
            args["storage_state"] = str(session_path)

        context = browser.new_context(**args)
        page = context.new_page()
        return browser, context, page

    def perform_login(self, page, email: str, password: str) -> bool:
        try:
            if "/event/add" not in page.url:
                page.goto(URLS["event_add"])
                page.wait_for_load_state("domcontentloaded")

            if "/select" in page.url or "Standort" in page.title():
                try: page.goto("https://raumreservation.ub.unibe.ch/set/1")
                except: pass

            if page.locator("#username").is_visible() or "eduid" in page.url:
                page.fill("#username", email)
                page.keyboard.press("Enter")
                human_sleep(1)
                if page.locator("#password").is_visible():
                    page.fill("#password", password)
                    page.keyboard.press("Enter")
                page.wait_for_load_state("networkidle")
                time.sleep(3)
            return True
        except: return False

    def execute_booking(self, tasks, accounts, preferred_rooms, simulation_mode, summary="Lernen"):
        self.logger.log("--- START: INTERNE BUCHUNG ---")
        successes = []
        acc_idx = 0
        
        for task in tasks:
            block_success = False
            for room_name in preferred_rooms:
                if block_success: break
                room_id = task["all_rooms"].get(room_name)
                if not room_id: continue

                acc = accounts[acc_idx % len(accounts)]
                acc_idx += 1
                session_file = APP_DIR / f"session_{acc.email.replace('@', '_')}.json"
                self.logger.log(f"Versuche: {task['start']}-{task['end']} ({room_name}) mit {acc.email}")

                try:
                    with sync_playwright() as p:
                        browser, context, page = self.get_context(p, session_path=session_file)
                        try:
                            if not self.perform_login(page, acc.email, acc.password): continue
                            context.storage_state(path=str(session_file))
                            
                            if "/event/add" not in page.url: page.goto(URLS["event_add"])
                            
                            page.evaluate(f"v => {{ var s=document.getElementById('event_room'); if(s) {{ s.value=v; s.dispatchEvent(new Event('change')); }} }}", room_id)
                            human_sleep(0.5)
                            page.fill("#event_startDate", f"{task['date']} {task['start']}")
                            page.keyboard.press("Enter")
                            
                            t1 = datetime.strptime(task["start"], "%H:%M")
                            t2 = datetime.strptime(task["end"], "%H:%M")
                            dur = int((t2 - t1).total_seconds() / 60)
                            
                            page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
                            page.evaluate("document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))")
                            page.fill("#event_title", summary)
                            try: page.check('input[name="event[purpose]"][value="Other"]') 
                            except: pass
                            
                            if not simulation_mode:
                                page.click("#event_submit")
                                try:
                                    page.wait_for_url(lambda u: "/event/add" not in u, timeout=5000)
                                    self.logger.log(f"ERFOLG: {room_name} gebucht!")
                                    block_success = True
                                except:
                                    if "konflikt" not in page.content().lower():
                                        block_success = True 

                            if block_success:
                                date_val = datetime.strptime(task["date"], "%d.%m.%Y").date()
                                successes.append({
                                    "start": datetime.combine(date_val, t1.time()), 
                                    "end": datetime.combine(date_val, t2.time()), 
                                    "room": room_name, 
                                    "account": acc.email
                                })
                        finally: browser.close()
                except Exception as e: self.logger.log(f"Error: {e}")
            if not block_success: self.logger.log(f"FEHLER: Block {task['start']} fehlgeschlagen.")
        return successes
