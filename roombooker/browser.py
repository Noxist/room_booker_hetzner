import time
import json
import os
import re
from playwright.sync_api import sync_playwright
from .config import URL_LOGIN, URL_SELECT, URL_SET_VONROLL, DEBUG_DIR, BASE_DIR

# --- HELPER FUNCTIONS ---
def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0

class BrowserEngine:
    def __init__(self, headless=True):
        self.headless = headless

    def _perform_login_logic(self, page, email, password):
        print(f"     [LOGIN] Starte Login für {email}...")
        try:
            page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=60000)
            
            try:
                page.wait_for_load_state("domcontentloaded")
            except:
                pass
            
            time.sleep(2)
            
            # Standort Fix
            if "select" in page.url or page.locator("text=Bibliothek wählen").count() > 0:
                 print("     [NAV] Standortwahl erkannt. Setze vonRoll...")
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
            
            # Edu-ID
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

    def scan_grid(self, date_str, allowed_rooms):
        d_parts = date_str.split(".")
        iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
        data = {r: [] for r in allowed_rooms}
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
            page = browser.new_page()
            try:
                url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
                page.goto(url)
                time.sleep(1)
                if "select" in page.url: 
                    page.goto("https://raumreservation.ub.unibe.ch/set/1")
                    page.goto(url)
                    time.sleep(1)
                
                raw = page.evaluate("""() => Array.from(document.querySelectorAll('rect[data-event-event-value]')).map(el => JSON.parse(el.getAttribute('data-event-event-value')))""")
                for e in raw:
                    r = e['roomName']
                    if r in data: 
                        data[r].append({"start": t2m(e['start'].split('T')[1][:5]), "end": t2m(e['end'].split('T')[1][:5])})
            except Exception as e:
                pass
            finally: 
                browser.close()
        return data

    def perform_booking(self, date_str, room, start_m, end_m, account):
        success = False
        error_msg = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
            page = browser.new_page()
            try:
                if not self._perform_login_logic(page, account['email'], account['password']):
                    print(f"     [BOOKING] Login failed for {account['email']}")
                    return False
                
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
                
                # Wait for response and check for errors
                time.sleep(2)
                content = page.content().lower()
                
                if "error" in content or "fehler" in content or "nicht verfügbar" in content:
                    print(f"     [BOOKING] Buchung fehlgeschlagen: Raum nicht verfügbar oder Fehler")
                    try:
                        page.screenshot(path=f"{DEBUG_DIR}/error_{int(time.time())}.png")
                    except:
                        pass
                    success = False
                elif "successfully" in content or "erfolgreich" in content or "event/add" not in page.url:
                    success = True
                    print(f"     [BOOKING] ✅ Erfolgreich: {room} {m2t(start_m)}-{m2t(end_m)}")
                else:
                    print(f"     [BOOKING] Unklarer Status für {room}")
                    
            except Exception as e:
                print(f"     [BOOKING ERROR] {e}")
                try:
                    page.screenshot(path=f"{DEBUG_DIR}/error_{int(time.time())}.png")
                except:
                    pass
            finally: 
                browser.close()
        return success

    def get_my_reservations(self, account):
        bookings = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            try:
                if self._perform_login_logic(page, account['email'], account['password']):
                    target_url = "https://raumreservation.ub.unibe.ch/reservation"
                    print(f"     [SCAN] Navigiere zu: {target_url}")
                    page.goto(target_url)
                    
                    try:
                        page.wait_for_load_state("networkidle")
                    except:
                        pass
                    
                    time.sleep(3) # Warten auf Tabelle
                    
                    # Holt alle Zellen-Texte der Tabelle
                    rows_data = page.evaluate("""() => {
                        return Array.from(document.querySelectorAll("table tbody tr")).map(row => {
                            return Array.from(row.querySelectorAll("td")).map(td => td.innerText.trim());
                        });
                    }""")
                    
                    print(f"     [SCAN] {len(rows_data)} Zeilen gefunden.")
                    
                    for cols in rows_data:
                        if not cols or len(cols) < 3: 
                            continue
                        
                        date_str = ""
                        start_time = ""
                        end_time = ""
                        room = ""
                        
                        # 1. Datum finden (DD.MM.YYYY) - FIX: Nur das Datum extrahieren!
                        for c in cols:
                            match = re.search(r"(\d{2}\.\d{2}\.\d{4})", c)
                            if match:
                                date_str = match.group(1) # Nur das Datum, ignoriere den Rest
                                break
                        
                        # 2. Zeiten finden (HH:MM)
                        times = []
                        for c in cols:
                            matches = re.findall(r"\d{2}:\d{2}", c)
                            times.extend(matches)
                        
                        if len(times) >= 2:
                            start_time = times[0]
                            end_time = times[1]
                        
                        # 3. Raum finden
                        for c in cols:
                            if "A-" in c or "D-" in c:
                                match = re.search(r"[AD]-\d+", c)
                                if match: room = match.group(0)
                                else: room = c
                                break
                        
                        if date_str and start_time and end_time and room:
                            print(f"     [FOUND] {date_str} {start_time}-{end_time} {room}")
                            bookings.append({
                                "date": date_str,
                                "start": start_time,
                                "end": end_time,
                                "room": room,
                                "account": account['email']
                            })
            except Exception as e: 
                print(f"     [SCAN ERROR] {e}")
            finally: 
                browser.close()
        
        self._save_to_debug_cache(bookings)
        return bookings

    def _save_to_debug_cache(self, new_bookings):
        cache_file = BASE_DIR / "last_scan.json"
        existing = []
        if cache_file.exists():
            try:
                with open(cache_file, "r") as f: existing = json.load(f)
            except: pass
        
        # Duplikate vermeiden
        existing_signatures = {f"{x['date']}_{x['start']}_{x['room']}_{x['account']}" for x in existing}
        for b in new_bookings:
            sig = f"{b['date']}_{b['start']}_{b['room']}_{b['account']}"
            if sig not in existing_signatures:
                existing.append(b)
        
        try:
            with open(cache_file, "w") as f: json.dump(existing, f, indent=2)
            print(f"     [DEBUG] Cache aktualisiert.")
        except: pass
