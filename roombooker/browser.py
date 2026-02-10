import time
from playwright.sync_api import sync_playwright
from .config import URL_LOGIN, URL_SELECT, URL_SET_VONROLL, DEBUG_DIR

def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0

class BrowserEngine:
    def __init__(self, headless=True):
        self.headless = headless

    def _fix_select_loop(self, page):
        """Erkennt die Standortwahl und klickt hart auf vonRoll."""
        if "select" in page.url or "set" in page.url:
            print("     [NAV FIX] Standortwahl erkannt. Erzwinge vonRoll...")
            page.goto(URL_SET_VONROLL)
            time.sleep(1)

    def login(self, page, email, password):
        print(f"     [LOGIN] {email}...")
        try:
            page.goto(URL_LOGIN, timeout=60000)
            self._fix_select_loop(page)

            # Check if already logged in
            if "/event/add" in page.url and "login" not in page.url:
                return True

            # Klicke Login Button falls Landing Page
            if page.locator("text=Login").count() > 0:
                page.click("text=Login")
            
            # Edu-ID
            if page.locator("#username").is_visible():
                page.fill("#username", email)
                page.keyboard.press("Enter")
                time.sleep(1)
                page.fill("#password", password)
                page.keyboard.press("Enter")
                
                # Warte auf Redirect
                try: page.wait_for_url("**/event/**", timeout=30000)
                except: pass
                
                self._fix_select_loop(page)
                return True
        except Exception as e:
            print(f"     [ERROR] Login fehlgeschlagen: {e}")
        return False

    def scan_grid(self, date_str, allowed_rooms):
        d_parts = date_str.split(".")
        iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
        data = {r: [] for r in allowed_rooms}
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            try:
                url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
                page.goto(url)
                self._fix_select_loop(page)
                
                # Rects auslesen
                try: page.wait_for_selector('rect[data-event-event-value]', timeout=5000)
                except: pass
                
                raw = page.evaluate("""() => Array.from(document.querySelectorAll('rect[data-event-event-value]')).map(el => JSON.parse(el.getAttribute('data-event-event-value')))""")
                
                for e in raw:
                    r = e['roomName']
                    if r in data:
                        data[r].append({"start": t2m(e['start'].split('T')[1][:5]), "end": t2m(e['end'].split('T')[1][:5])})
            finally:
                browser.close()
        return data

    def perform_booking(self, date_str, room, start_m, end_m, account):
        success = False
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()
            try:
                if self.login(page, account['email'], account['password']):
                    page.goto(URL_LOGIN)
                    self._fix_select_loop(page)
                    
                    # Formular füllen
                    page.wait_for_selector("#event_room", timeout=10000)
                    
                    # Raum wählen via JS
                    found = page.evaluate(f"""(r) => {{
                        const s = document.querySelector('#event_room');
                        for(let i=0; i<s.options.length; i++) {{
                            if(s.options[i].innerText.includes(r)) {{
                                s.selectedIndex = i; s.dispatchEvent(new Event('change')); return true;
                            }}
                        }} return false;
                    }}""", room)
                    
                    if found:
                        time.sleep(1)
                        page.fill("#event_startDate", f"{date_str} {m2t(start_m)}")
                        page.keyboard.press("Enter")
                        page.fill("#event_duration", str(end_m - start_m))
                        page.keyboard.press("Enter")
                        page.fill("#event_title", "Lernen")
                        try: page.check('input[name="event[purpose]"][value="Other"]')
                        except: pass
                        
                        page.click("#event_submit")
                        time.sleep(3)
                        
                        if "event/add" not in page.url or "successfully" in page.content():
                            success = True
            except Exception as e:
                print(f"     [ERROR] Buchung abgebrochen: {e}")
                # Screenshot bei Fehler
                page.screenshot(path=f"{DEBUG_DIR}/error_{int(time.time())}.png")
            finally:
                browser.close()
        return success
