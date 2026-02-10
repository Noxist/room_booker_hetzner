import time
import json
from playwright.sync_api import sync_playwright
from .config import URL_LOGIN, URL_SELECT, URL_SET_VONROLL, DEBUG_DIR

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
            time.sleep(2)
            
            if "select" in page.url or page.locator("text=Bibliothek wählen").count() > 0:
                 print("     [LOGIN] Standortwahl erkannt. Setze vonRoll...")
                 page.goto("https://raumreservation.ub.unibe.ch/set/1") 
                 time.sleep(1)
                 page.goto("https://raumreservation.ub.unibe.ch/event/add")
                 time.sleep(2)

            if "/event/add" in page.url and "wayf" not in page.url and "login" not in page.url:
                return True
            
            if page.locator("text=Login").count() > 0: 
                page.click("text=Login")
            elif page.locator(".timeline-cell-clickable").count() > 0: 
                page.locator(".timeline-cell-clickable").first.click()

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
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
            page = browser.new_page()
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
                    try: page.check('input[name="event[purpose]"][value="Other"]')
                    except: pass
                    
                    page.click("#event_submit")
                    
                    try: 
                        page.wait_for_url(lambda u: "event/add" not in u, timeout=10000)
                        success = True
                    except: 
                        if "successfully" in page.content(): success = True
            except Exception as e:
                print(f"     [BOOKING ERROR] {e}")
                try: page.screenshot(path=f"{DEBUG_DIR}/error_{int(time.time())}.png")
                except: pass
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
                    # FIX: URL korrigiert (reservation statt reservations)
                    target_url = "https://raumreservation.ub.unibe.ch/reservation"
                    print(f"     [SCAN] Navigiere zu: {target_url}")
                    page.goto(target_url)
                    page.wait_for_load_state("networkidle")
                    time.sleep(3) # Warten auf Tabelle
                    
                    rows = page.locator("tbody tr").all()
                    print(f"     [SCAN] Gefundene Zeilen: {len(rows)}")
                    
                    for row in rows:
                        txt = row.inner_text().replace("\n", " ")
                        # Parsing Logik
                        parts = txt.split()
                        # Erwarte Format ca: DD.MM.YYYY HH:MM-HH:MM Raum ...
                        if len(parts) > 3 and "." in parts[0] and ":" in parts[1]:
                            date_str = parts[0]
                            time_range = parts[1]
                            room = "Unbekannt"
                            if "A-" in txt: room = "A-" + txt.split("A-")[1].split()[0]
                            elif "D-" in txt: room = "D-" + txt.split("D-")[1].split()[0]
                            
                            bookings.append({
                                "date": date_str, 
                                "time": time_range, 
                                "room": room, 
                                "account": account['email']
                            })
            except Exception as e: 
                print(f"     [SCAN ERROR] {e}")
            finally: 
                browser.close()
        return bookings
