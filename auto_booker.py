import sys
import json
import time
import os
import argparse
import traceback
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir

# --- CONFIG ---
DATA_DIR = resolve_data_dir()
HISTORY_FILE = DATA_DIR / "booking_history.json"
WEIGHTS_FILE = DATA_DIR / "weights.json"
CATEGORIES_FILE = DATA_DIR / "categories.json"
GOOGLE_CREDS = DATA_DIR / "google_credentials.json"
GOOGLE_TOKEN = DATA_DIR / "token.json"

# --- HELPERS ---
def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f: return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

# --- GOOGLE CALENDAR SYNC (Embedded) ---
class CalendarSync:
    def __init__(self):
        self.service = None
        self.calendar_id = 'primary'
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            SCOPES = ['https://www.googleapis.com/auth/calendar']
            creds = None
            if os.path.exists(GOOGLE_TOKEN):
                creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN, SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if os.path.exists(GOOGLE_CREDS):
                        flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDS, SCOPES)
                        creds = flow.run_local_server(port=0)
                    else:
                        print("[CALENDAR] Warnung: google_credentials.json fehlt. Kein Sync.")
                        return
                with open(GOOGLE_TOKEN, 'w') as token:
                    token.write(creds.to_json())

            self.service = build('calendar', 'v3', credentials=creds)
            print("[CALENDAR] Verbunden ✅")
        except ImportError:
            print("[CALENDAR] Google Libs fehlen (pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib).")
        except Exception as e:
            print(f"[CALENDAR] Fehler beim Init: {e}")

    def add_event(self, title, date_str, start_time, end_time, description=""):
        if not self.service: return
        try:
            # Check Duplicates (Simpel: Suche Events am gleichen Tag mit gleichem Titel)
            d_iso = datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
            start_dt = f"{d_iso}T{start_time}:00"
            end_dt = f"{d_iso}T{end_time}:00"
            
            events_result = self.service.events().list(calendarId=self.calendar_id, timeMin=f"{d_iso}T00:00:00Z", timeMax=f"{d_iso}T23:59:59Z", singleEvents=True).execute()
            for e in events_result.get('items', []):
                if e['summary'] == title and e['start'].get('dateTime', '').startswith(start_dt[:16]):
                    print(f"[CALENDAR] Event existiert bereits: {title}")
                    return

            event = {
                'summary': title,
                'description': description,
                'start': {'dateTime': start_dt, 'timeZone': 'Europe/Zurich'},
                'end': {'dateTime': end_dt, 'timeZone': 'Europe/Zurich'},
            }
            self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            print(f"[CALENDAR] Event erstellt: {title} ({start_time}-{end_time})")
        except Exception as e:
            print(f"[CALENDAR ERROR] {e}")

# --- INTELLIGENZ ---
class BookingOptimizer:
    def __init__(self):
        self.history = load_json(HISTORY_FILE)
        self.weights = load_json(WEIGHTS_FILE) or {"totalCoveredMin": 0.001, "stabilityBonus": 0.5, "preferredRoomBonus": 5}

    def get_booked_slots(self, date_str): return self.history.get(date_str, [])

    def calculate_gaps(self, date_str, req_start_m, req_end_m):
        booked = sorted(self.get_booked_slots(date_str), key=lambda x: x['start'])
        gaps = []
        curr = req_start_m
        for b in booked:
            if b['end'] <= curr: continue
            if b['start'] > curr:
                end_gap = min(b['start'], req_end_m)
                if end_gap - curr >= 30: gaps.append((curr, end_gap))
                curr = max(curr, b['end'])
            else: curr = max(curr, b['end'])
            if curr >= req_end_m: break
        if curr < req_end_m: gaps.append((curr, req_end_m))
        return gaps

    def get_available_accounts(self, date_str, start_m, end_m, all_accounts):
        blocked_emails = set()
        for h in self.history.get(date_str, []):
            if not (h['end'] <= start_m or h['start'] >= end_m):
                blocked_emails.add(h['account'])
        return [a for a in all_accounts if a.email not in blocked_emails]

    def score_candidate(self, room_name, start_m, end_m, date_str):
        duration = end_m - start_m
        score = duration * self.weights.get("totalCoveredMin", 0.001)
        for h in self.history.get(date_str, []):
            if h['room'] == room_name:
                score += self.weights.get("stabilityBonus", 0.5) * duration
                break
        if "206" in room_name or "204" in room_name: score += self.weights.get("preferredRoomBonus", 5)
        return score

    def save_booking(self, date_str, room, start_m, end_m, account):
        if date_str not in self.history: self.history[date_str] = []
        self.history[date_str].append({"room": room, "start": start_m, "end": end_m, "account": account})
        save_json(HISTORY_FILE, self.history)

# --- BROWSER ACTIONS ---
def perform_login(page, email, password):
    print(f"   [LOGIN] Starte Login für {email}...")
    try:
        page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=60000)
        time.sleep(2)
        if "select" in page.url or page.locator("text=Bibliothek wählen").count() > 0:
             print("   [LOGIN DEBUG] Standortwahl erkannt (/select). Setze vonRoll...")
             page.goto("https://raumreservation.ub.unibe.ch/set/1") 
             time.sleep(1)
             page.goto("https://raumreservation.ub.unibe.ch/event/add")
             time.sleep(2)

        if "/event/add" in page.url and "wayf" not in page.url and "login" not in page.url: return True
        
        if page.locator("text=Login").count() > 0: page.click("text=Login")
        elif page.locator(".timeline-cell-clickable").count() > 0: page.locator(".timeline-cell-clickable").first.click()

        if "wayf" in page.url or "login" in page.url or "eduid" in page.url:
            page.wait_for_selector("#username", state="visible", timeout=10000)
            page.fill("#username", email)
            page.keyboard.press("Enter")
            page.wait_for_selector("#password", state="visible", timeout=10000)
            time.sleep(1) 
            page.fill("#password", password)
            page.keyboard.press("Enter")
            page.wait_for_url("**/event/**", timeout=30000)
            print("   [LOGIN] Erfolgreich! ✅")
            return True
    except Exception as e:
        print(f"   [LOGIN ERROR] {e}")
    return False

def scan_reservations(page):
    """Liest die Tabelle 'Meine Reservationen' aus."""
    bookings = []
    try:
        page.goto("https://raumreservation.ub.unibe.ch/reservation", wait_until="domcontentloaded")
        time.sleep(2)
        rows = page.locator("tbody tr").all()
        print(f"   [SCAN] Finde {len(rows)} Einträge in Tabelle...")
        for row in rows:
            txt = row.inner_text()
            # Erwarte Format: Datum Zeit Raum ...
            # Simple Heuristik: Suche nach Datumsformat DD.MM.YYYY
            parts = txt.split()
            if len(parts) > 3 and "." in parts[0] and ":" in parts[1]:
                date_str = parts[0]
                times = parts[1].split("-")
                if len(times) == 2:
                    room = "Unbekannt"
                    for p in parts: 
                        if "A-" in p or "D-" in p: room = p; break
                    bookings.append({"date": date_str, "start": times[0], "end": times[1], "room": room})
    except Exception as e: print(f"   [SCAN ERROR] {e}")
    return bookings

def scan_rooms(iso_date, allowed_rooms):
    data = {r: [] for r in allowed_rooms}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page()
        try:
            url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            page.goto(url); time.sleep(1)
            if "select" in page.url: page.goto("https://raumreservation.ub.unibe.ch/set/1"); page.goto(url); time.sleep(1)
            raw = page.evaluate("""() => Array.from(document.querySelectorAll('rect[data-event-event-value]')).map(el => JSON.parse(el.getAttribute('data-event-event-value')))""")
            for e in raw:
                r = e['roomName']
                if r in data: data[r].append({"start": t2m(e['start'].split('T')[1][:5]), "end": t2m(e['end'].split('T')[1][:5])})
        except: pass
        finally: browser.close()
    return data

def find_slot(rooms_data, req_start, req_end, optimizer, date_str):
    best = None
    for room, bookings in rooms_data.items():
        sorted_b = sorted(bookings, key=lambda x: x['start'])
        limit = req_end
        for b in sorted_b:
            if b['end'] <= req_start: continue
            if b['start'] < limit: limit = b['start']
        actual_end = min(limit, req_start + 240)
        if (actual_end - req_start) >= 30:
            score = optimizer.score_candidate(room, req_start, actual_end, date_str)
            cand = {"room": room, "start": req_start, "end": actual_end, "score": score}
            if not best or score > best['score']: best = cand
    return best

def execute_booking_step(step, account, date_str):
    print(f"   >>> Buche {step['room']} ({m2t(step['start'])}-{m2t(step['end'])}) mit {account.email}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page()
        try:
            if perform_login(page, account.email, account.password):
                page.goto("https://raumreservation.ub.unibe.ch/event/add")
                page.wait_for_selector("#event_room", timeout=30000)
                page.evaluate(f"document.querySelector('#event_room').value = '{step['room']}';") # Quick Hack select
                # Fallback JS Select Loop wenn value failt
                page.evaluate(f"""(r) => {{ const s = document.querySelector('#event_room'); for(let i=0; i<s.options.length; i++) {{ if(s.options[i].innerText.includes(r)) {{ s.selectedIndex = i; s.dispatchEvent(new Event('change')); }} }} }}""", step['room'])
                
                time.sleep(0.5)
                page.fill("#event_startDate", f"{date_str} {m2t(step['start'])}")
                page.keyboard.press("Enter")
                time.sleep(0.5)
                page.fill("#event_duration", str(step['end'] - step['start']))
                page.keyboard.press("Enter")
                page.fill("#event_title", "Lernen")
                try: page.check('input[name="event[purpose]"][value="Other"]')
                except: pass
                page.click("#event_submit")
                
                try: page.wait_for_url(lambda u: "event/add" not in u, timeout=10000); return True
                except: return "successfully" in page.content()
        except Exception as e: print(f"[ERROR] {e}")
        finally: browser.close()
    return False

# --- JOB LOGIC ---
def execute_job(date_str, start_time, end_time, category_key, num_accounts):
    print(f"\n=== JOB START: {date_str} {start_time}-{end_time} ===")
    opt = BookingOptimizer()
    cal = CalendarSync()
    
    categories = load_json(CATEGORIES_FILE)
    target_rooms = categories.get(category_key, categories.get("default", {})).get("rooms", [])
    if not target_rooms: print(f"[ERROR] Keine Räume gefunden."); return

    req_start = t2m(start_time); req_end = t2m(end_time)
    gaps = opt.calculate_gaps(date_str, req_start, req_end)
    if not gaps: print("[INFO] Alles abgedeckt! ✅"); return

    print(f"[LOGIC] Lücken: {[f'{m2t(s)}-{m2t(e)}' for s,e in gaps]}")
    rooms_state = scan_rooms(datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d"), target_rooms)
    all_accs = load_accounts(DATA_DIR / "settings.json")
    if isinstance(num_accounts, int): all_accs = all_accs[:num_accounts]

    for gap_start, gap_end in gaps:
        current_time = gap_start
        while current_time < gap_end:
            avail_accs = opt.get_available_accounts(date_str, current_time, min(current_time+240, gap_end), all_accs)
            if not avail_accs: print(f"[WARN] Keine Accounts mehr!"); break
            
            best_slot = find_slot(rooms_state, current_time, gap_end, opt, date_str)
            if not best_slot: print(f"[WARN] Kein Raum!"); break
            
            slot_filled = False
            for acc in avail_accs:
                if execute_booking_step(best_slot, acc, date_str):
                    print(f"[SUCCESS] {best_slot['room']} gebucht!")
                    opt.save_booking(date_str, best_slot['room'], best_slot['start'], best_slot['end'], acc.email)
                    cal.add_event(f"Lernen: {best_slot['room']}", date_str, m2t(best_slot['start']), m2t(best_slot['end']), f"Account: {acc.email}")
                    current_time = best_slot['end']
                    slot_filled = True
                    break
            
            if not slot_filled:
                print("[FAIL] Gap konnte nicht gefüllt werden."); current_time += 30 

def sync_all_calendars():
    print("\n=== START FULL SYNC ===")
    cal = CalendarSync()
    all_accs = load_accounts(DATA_DIR / "settings.json")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for acc in all_accs:
            print(f">> Scanne Account: {acc.email}")
            page = browser.new_page()
            try:
                if perform_login(page, acc.email, acc.password):
                    bookings = scan_reservations(page)
                    for b in bookings:
                        cal.add_event(f"Lernen: {b['room']}", b['date'], b['start'], b['end'], f"Importiert von {acc.email}")
            except Exception as e: print(f"   [ERROR] {e}")
            finally: page.close()
        browser.close()
    print("=== SYNC COMPLETE ===")

def wizard():
    print("\n" + "="*30)
    print("   AUTO BOOKER WIZARD 🧙‍♂️")
    print("="*30)
    print("1. Neue Buchung (Smart)")
    print("2. Manueller Sync aller Accounts -> Google Cal")
    print("3. Exit")
    
    choice = input("\nWahl: ").strip()
    
    if choice == "1":
        d_def = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
        date_str = input(f"Datum ({d_def}): ") or d_def
        start_t = input("Start (08:00): ") or "08:00"
        end_t = input("Ende (18:00): ") or "18:00"
        cat = input("Kategorie (default): ") or "default"
        accs = input("Anzahl Accounts (4): ") or "4"
        execute_job(date_str, start_t, end_t, cat, int(accs))
        
    elif choice == "2":
        sync_all_calendars()
    
    else:
        print("Bye!")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        wizard()
    elif len(sys.argv) > 4:
        execute_job(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
    else:
        # Default fallback to wizard if no args
        wizard()
