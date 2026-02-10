import time
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0

class BrowserEngine:
    def __init__(self, headless=True):
        self.headless = headless

    def _handle_nav(self, page):
        """Hilft bei Navigation und Standortwahl"""
        try:
            # Check auf Standortwahl URL oder Text
            if "select" in page.url or page.locator("text=Bibliothek wählen").count() > 0:
                 print("   [NAV] Standortwahl erkannt -> Setze vonRoll")
                 page.goto("https://raumreservation.ub.unibe.ch/set/1") 
                 time.sleep(1)
        except: pass

    def login(self, page, email, password):
        print(f"   [LOGIN] Starte für {email}...")
        try:
            page.goto("https://raumreservation.ub.unibe.ch/reservation", timeout=60000)
            self._handle_nav(page)
            
            # Check ob schon eingeloggt
            if "reservation" in page.url and "login" not in page.url:
                print("   [LOGIN] Bereits eingeloggt.")
                return True

            # Klick auf Login Button falls nötig
            if page.locator("text=Login").count() > 0: 
                page.click("text=Login")
            elif page.locator(".timeline-cell-clickable").count() > 0:
                page.locator(".timeline-cell-clickable").first.click()
            
            # Edu-ID Login Maske
            if "wayf" in page.url or "login" in page.url or "eduid" in page.url:
                page.wait_for_selector("#username", state="visible", timeout=10000)
                page.fill("#username", email)
                page.keyboard.press("Enter")
                
                # Passwort Feld kann kurz dauern
                page.wait_for_selector("#password", state="visible", timeout=10000)
                time.sleep(1) 
                page.fill("#password", password)
                page.keyboard.press("Enter")
                
                # Warte auf Redirect zurück zur App
                page.wait_for_url("**/reservation**", timeout=40000)
                print("   [LOGIN] Erfolgreich ✅")
                return True
        except Exception as e:
            print(f"   [LOGIN ERROR] {e}")
        return False

    def scan_user_reservations(self, page):
        """Liest die Tabelle 'Meine Reservationen' aus"""
        bookings = []
        print("   [SCAN] Lese Tabelle...")
        try:
            # Sicherstellen, dass wir auf der richtigen Seite sind
            if "reservation" not in page.url:
                page.goto("https://raumreservation.ub.unibe.ch/reservation")
            
            time.sleep(2) # Warten auf Table Render
            
            rows = page.locator("tbody tr").all()
            if not rows:
                print("   [SCAN] Keine Zeilen gefunden (oder Ladefehler).")
                return []

            for row in rows:
                txt = row.inner_text().replace("\n", " ")
                # Regex Suche nach Datum, Zeit und Raum
                # Bsp: "20.02.2026 08:00 - 12:00 ... A-204"
                time_match = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", txt)
                room_match = re.search(r"\b([A-D]-\d{3})\b", txt)
                
                if time_match and room_match:
                    d_str, t_start, t_end = time_match.groups()
                    bookings.append({
                        "date": d_str,
                        "start": t_start,
                        "end": t_end,
                        "room": room_match.group(1)
                    })
        except Exception as e:
            print(f"   [SCAN ERROR] {e}")
        return bookings

    def perform_booking(self, page, account, slot, date_str):
        if not self.login(page, account['email'], account['password']): return False
        try:
            page.goto("https://raumreservation.ub.unibe.ch/event/add")
            page.wait_for_selector("#event_room", timeout=20000)
            
            # Raum wählen (JS Hack für Dropdown)
            found = page.evaluate(f"""(r) => {{
                const s = document.querySelector('#event_room');
                for(let i=0; i<s.options.length; i++) {{
                    if(s.options[i].innerText.includes(r)) {{
                        s.selectedIndex = i; s.dispatchEvent(new Event('change')); return true;
                    }}
                }} return false;
            }}""", slot['room'])
            
            if not found: 
                print(f"   [BOOK] Raum {slot['room']} im Dropdown nicht gefunden.")
                return False
            
            time.sleep(0.5)
            page.fill("#event_startDate", f"{date_str} {m2t(slot['start'])}")
            page.keyboard.press("Enter")
            time.sleep(0.5)
            page.fill("#event_duration", str(slot['end'] - slot['start']))
            page.keyboard.press("Enter")
            page.fill("#event_title", "Lernen")
            try: page.check('input[name="event[purpose]"][value="Other"]')
            except: pass
            
            page.click("#event_submit")
            
            # Erfolg prüfen
            try: 
                page.wait_for_url(lambda u: "event/add" not in u, timeout=10000)
                return True
            except: 
                return "successfully" in page.content()
        except Exception as e:
            print(f"   [BOOK ERROR] {e}")
            return False
    
    def scan_available_rooms(self, browser, iso_date, target_rooms):
        data = {r: [] for r in target_rooms}
        # Wichtig: User Agent setzen, sonst blockiert Uni evtl. Headless
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()
        try:
            url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            page.goto(url)
            self._handle_nav(page)
            if "select" in page.url: # Double check
                page.goto("https://raumreservation.ub.unibe.ch/set/1"); page.goto(url)
            
            time.sleep(1)
            raw = page.evaluate("""() => Array.from(document.querySelectorAll('rect[data-event-event-value]')).map(el => JSON.parse(el.getAttribute('data-event-event-value')))""")
            for e in raw:
                r = e['roomName']
                if r in data:
                    data[r].append({"start": t2m(e['start'].split('T')[1][:5]), "end": t2m(e['end'].split('T')[1][:5])})
        except: pass
        finally: 
            page.close()
            context.close()
        return data
