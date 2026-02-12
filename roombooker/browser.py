import time
import json
import os
import re
from playwright.sync_api import sync_playwright
from .config import URL_LOGIN, URL_SELECT, URL_SET_VONROLL, DEBUG_DIR, BASE_DIR, HEADLESS

def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: 
        h, m = map(int, t_str.split(":"))
        return h * 60 + m
    except: 
        return 0

class BrowserEngine:
    def __init__(self, base_dir=None, headless=None):
        self.headless = headless if headless is not None else HEADLESS
        self.base_dir = base_dir or BASE_DIR

    def _perform_login_logic(self, page, email, password):
        print(f"     [LOGIN] Starte Login für {email}...")
        try:
            page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=60000)
            
            # Syntax-Fix: Mehrzeilig
            try:
                page.wait_for_load_state("domcontentloaded")
            except:
                pass
            
            time.sleep(2)
            
            # Standort Fix
            if "select" in page.url or page.locator("text=Bibliothek wählen").count() > 0:
                 print("     [NAV] Wähle Bibliothek vonRoll...")
                 page.goto("https://raumreservation.ub.unibe.ch/set/1") 
                 time.sleep(1)
                 page.goto("https://raumreservation.ub.unibe.ch/event/add")
                 try:
                     page.wait_for_load_state("domcontentloaded")
                 except:
                     pass
                 time.sleep(3)

            if "/event/add" in page.url and "wayf" not in page.url and "login" not in page.url:
                return True
            
            if page.locator("text=Login").count() > 0: 
                page.click("text=Login")
                time.sleep(2)
            
            if "wayf" in page.url or "login" in page.url or "eduid" in page.url:
                page.wait_for_selector("#username", state="visible", timeout=10000)
                page.fill("#username", email)
                page.keyboard.press("Enter")
                
                page.wait_for_selector("#password", state="visible", timeout=10000)
                time.sleep(1) 
                page.fill("#password", password)
                page.keyboard.press("Enter")
                
                page.wait_for_url("**/event/**", timeout=30000)
                print("     [LOGIN] Erfolgreich! ✅")
                return True
        except Exception as e:
            print(f"     [LOGIN ERROR] {e}")
        return False

    def scan_reservations(self, account):
        bookings = []
        print(f"[SCAN] Prüfe Reservationen für {account['email']}...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless, 
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            try:
                if self._perform_login_logic(page, account['email'], account['password']):
                    # KORREKTER LINK: Einzahl /reservation
                    target_url = "https://raumreservation.ub.unibe.ch/reservation"
                    page.goto(target_url)
                    
                    try:
                        page.wait_for_selector("table", timeout=5000)
                    except:
                        pass
                    
                    rows = page.query_selector_all("tbody tr")
                    for row in rows:
                        text = row.inner_text()
                        try:
                            # Regex Parsing
                            date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
                            time_match = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", text)
                            room_match = re.search(r"([A-Z]-\d{3})", text)

                            if date_match and time_match:
                                b = {
                                    "date": date_match.group(1),
                                    "start": time_match.group(1),
                                    "end": time_match.group(2),
                                    "room": room_match.group(1) if room_match else "Unbekannt",
                                    "account": account['email']
                                }
                                bookings.append(b)
                                print(f"     [FOUND] {b['date']} | {b['start']}-{b['end']} | {b['room']}")
                        except:
                            continue
            except Exception as e:
                print(f"     [SCAN ERROR] {e}")
            finally:
                browser.close()
        
        return bookings

    def perform_booking(self, date_str, room, start_m, end_m, account):
        success = False
        print(f"[BROWSER] Starte Buchung für {room}...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless, 
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            
            try:
                if self._perform_login_logic(page, account['email'], account['password']):
                    page.goto("https://raumreservation.ub.unibe.ch/event/add")
                    page.wait_for_selector("#event_room", timeout=30000)
                    
                    page.evaluate(f"document.querySelector('#event_room').value = '{room}';")
                    page.evaluate(f"""(r) => {{ 
                        const s = document.querySelector('#event_room'); 
                        for(let i=0; i<s.options.length; i++) {{ 
                            if(s.options[i].innerText.includes(r)) {{ 
                                s.selectedIndex = i; s.dispatchEvent(new Event('change')); 
                            }} 
                        }} 
                    }}""", room)
                    
                    time.sleep(0.5)
                    page.fill("#event_startDate", f"{date_str} {m2t(start_m)}")
                    page.keyboard.press("Enter")
                    time.sleep(0.5)
                    page.fill("#event_duration", str(end_m - start_m))
                    page.keyboard.press("Enter")
                    page.fill("#event_title", "Lernen")
                    
                    try:
                        page.check('input[name="event[purpose]"][value="Other"]')
                    except:
                        pass
                    
                    page.click("#event_submit")
                    
                    try: 
                        page.wait_for_url(lambda u: "event/add" not in u, timeout=10000)
                        success = True
                    except: 
                        if "successfully" in page.content(): success = True
            except Exception as e:
                print(f"     [BOOKING ERROR] {e}")
                try:
                    page.screenshot(path=f"{DEBUG_DIR}/error_{int(time.time())}.png")
                except:
                    pass
            finally: 
                browser.close()
        return success

    # Kompatibilitäts-Wrapper
    def perform_booking_wrapper(self, account, date_str, slot):
        start_m = t2m(slot['start'])
        end_m = t2m(slot['end'])
        return self.perform_booking(date_str, slot['room'], start_m, end_m, account)
