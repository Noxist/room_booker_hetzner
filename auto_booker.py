import sys
import json
import time
import os
import traceback
from datetime import datetime
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir

# --- CONFIG ---
DATA_DIR = resolve_data_dir()
HISTORY_FILE = DATA_DIR / "booking_history.json"
WEIGHTS_FILE = DATA_DIR / "weights.json"
CATEGORIES_FILE = DATA_DIR / "categories.json"

print(f"[DEBUG] DATA_DIR ist: {DATA_DIR}")

def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f: return json.load(f)
    print(f"[DEBUG] Datei nicht gefunden: {path} (Nutze Defaults)")
    return {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

# --- INTELLIGENZ ---
class BookingOptimizer:
    def __init__(self):
        self.history = load_json(HISTORY_FILE)
        self.weights = load_json(WEIGHTS_FILE)
        if not self.weights:
            self.weights = {"totalCoveredMin": 0.001, "stabilityBonus": 0.5, "preferredRoomBonus": 5}

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
        day_history = self.history.get(date_str, [])
        for h in day_history:
            if not (h['end'] <= start_m or h['start'] >= end_m):
                blocked_emails.add(h['account'])
        return [a for a in all_accounts if a.email not in blocked_emails]

    def score_candidate(self, room_name, start_m, end_m, date_str):
        duration = end_m - start_m
        score = duration * self.weights.get("totalCoveredMin", 0.001)
        day_history = self.history.get(date_str, [])
        for h in day_history:
            if h['room'] == room_name:
                score += self.weights.get("stabilityBonus", 0.5) * duration
                break
        if "206" in room_name or "204" in room_name: score += self.weights.get("preferredRoomBonus", 5)
        return score

    def save_booking(self, date_str, room, start_m, end_m, account):
        if date_str not in self.history: self.history[date_str] = []
        self.history[date_str].append({"room": room, "start": start_m, "end": end_m, "account": account})
        save_json(HISTORY_FILE, self.history)

# --- LOGIN & BROWSER ---

def perform_login(page, email, password):
    print(f"   [LOGIN] Starte Login für {email}...")
    try:
        page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=60000)
        time.sleep(2)
        
        # --- FIX: STANDORTWAHL ABFANGEN ---
        # Wir prüfen URL und Page Content, um sicher zu sein
        if "select" in page.url or page.locator("text=Bibliothek wählen").count() > 0:
             print("   [LOGIN DEBUG] Standortwahl erkannt (/select). Setze vonRoll...")
             page.goto("https://raumreservation.ub.unibe.ch/set/1") # 1 = vonRoll
             time.sleep(1)
             page.goto("https://raumreservation.ub.unibe.ch/event/add")
             time.sleep(2)
        # ----------------------------------

        print(f"   [LOGIN DEBUG] URL ist: {page.url}")

        # Fall 1: Bereits eingeloggt
        if "/event/add" in page.url and "wayf" not in page.url and "login" not in page.url:
            print("   [LOGIN] Bereits eingeloggt.")
            return True

        # Fall 2: Landing Page -> Klicke Login
        if page.locator("text=Login").count() > 0:
            print("   [LOGIN DEBUG] 'Login' Text gefunden, klicke...")
            page.click("text=Login")
            time.sleep(2)
        elif page.locator(".timeline-cell-clickable").count() > 0:
             print("   [LOGIN DEBUG] Timeline Cell gefunden, klicke...")
             page.locator(".timeline-cell-clickable").first.click()

        # Fall 3: Edu-ID / WAYF Maske
        if "wayf" in page.url or "login" in page.url or "eduid" in page.url:
            print("   [LOGIN DEBUG] Edu-ID Maske erkannt.")
            
            # Username
            page.wait_for_selector("#username", state="visible", timeout=10000)
            page.fill("#username", email)
            page.keyboard.press("Enter")
            print("   [LOGIN DEBUG] Username eingegeben.")
            
            # Password
            page.wait_for_selector("#password", state="visible", timeout=10000)
            time.sleep(1) 
            page.fill("#password", password)
            page.keyboard.press("Enter")
            print("   [LOGIN DEBUG] Passwort eingegeben.")
            
            # Warten auf Redirect
            print("   [LOGIN DEBUG] Warte auf Redirect...")
            page.wait_for_url("**/event/**", timeout=30000)
            print("   [LOGIN] Erfolgreich! ✅")
            return True
            
    except Exception as e:
        print(f"   [FATAL LOGIN ERROR] {e}")
        try: page.screenshot(path="login_fatal.png")
        except: pass
        print("   [INFO] Screenshot gespeichert: login_fatal.png")
    return False

def scan_rooms(iso_date, allowed_rooms):
    data = {r: [] for r in allowed_rooms}
    with sync_playwright() as p:
        print("[SCAN] Starte Browser Scan...")
        # Stealth Args
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
        try:
            url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(2)
            
            # Auch hier Standortwahl Fix
            if "select" in page.url:
                 page.goto("https://raumreservation.ub.unibe.ch/set/1")
                 page.goto(url)
                 time.sleep(1)

            raw = page.evaluate("""() => Array.from(document.querySelectorAll('rect[data-event-event-value]')).map(el => JSON.parse(el.getAttribute('data-event-event-value')))""")
            for e in raw:
                r = e['roomName']
                if r in data:
                    data[r].append({"start": t2m(e['start'].split('T')[1][:5]), "end": t2m(e['end'].split('T')[1][:5])})
            print(f"[SCAN] Scan abgeschlossen. {len(raw)} Events gefunden.")
        except Exception as e: print(f"[SCAN ERROR] {e}")
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
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        success = False
        try:
            if perform_login(page, account.email, account.password):
                page.goto("https://raumreservation.ub.unibe.ch/event/add", wait_until="domcontentloaded")
                page.wait_for_selector("#event_room", timeout=30000)
                
                found = page.evaluate(f"""(r) => {{
                    const s = document.querySelector('#event_room');
                    for(let i=0; i<s.options.length; i++) {{
                        if(s.options[i].innerText.includes(r)) {{
                            s.selectedIndex = i; s.dispatchEvent(new Event('change')); return true;
                        }}
                    }} return false;
                }}""", step['room'])
                
                if found:
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
                    try: 
                        page.wait_for_url(lambda u: "event/add" not in u, timeout=10000)
                        success = True
                    except:
                        if "successfully" in page.content(): success = True
        except Exception as e:
            print(f"[ERROR IN BOOKING] {e}")
            try: page.screenshot(path="booking_error.png")
            except: pass
        finally: browser.close()
        return success

def execute_job(date_str, start_time, end_time, category_key, num_accounts):
    print(f"\n=== JOB START: {date_str} {start_time}-{end_time} ===")
    opt = BookingOptimizer()
    
    categories = load_json(CATEGORIES_FILE)
    target_rooms = categories.get(category_key, categories.get("default", {})).get("rooms", [])
    if not target_rooms: print(f"[ERROR] Keine Räume gefunden."); return

    d_parts = date_str.split(".")
    iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
    req_start = t2m(start_time); req_end = t2m(end_time)
    
    gaps = opt.calculate_gaps(date_str, req_start, req_end)
    if not gaps: print("[INFO] Alles abgedeckt! ✅"); return

    print(f"[LOGIC] Lücken: {[f'{m2t(s)}-{m2t(e)}' for s,e in gaps]}")
    rooms_state = scan_rooms(iso_date, target_rooms)
    all_accs = load_accounts(DATA_DIR / "settings.json")
    
    if isinstance(num_accounts, int): 
        print(f"[INFO] Nutze {num_accounts} Accounts.")
        all_accs = all_accs[:num_accounts]

    for gap_start, gap_end in gaps:
        current_time = gap_start
        while current_time < gap_end:
            avail_accs = opt.get_available_accounts(date_str, current_time, min(current_time+240, gap_end), all_accs)
            if not avail_accs: print(f"[WARN] Keine Accounts mehr!"); break
            
            best_slot = find_slot(rooms_state, current_time, gap_end, opt, date_str)
            if not best_slot: print(f"[WARN] Kein Raum!"); break
            
            # Account Rotation
            slot_filled = False
            for acc in avail_accs:
                if execute_booking_step(best_slot, acc, date_str):
                    print(f"[SUCCESS] {best_slot['room']} gebucht!")
                    opt.save_booking(date_str, best_slot['room'], best_slot['start'], best_slot['end'], acc.email)
                    current_time = best_slot['end']
                    slot_filled = True
                    break
                else:
                    print(f"[WARN] Login/Buchung fehlgeschlagen für {acc.email}. Probiere nächsten...")
            
            if not slot_filled:
                print("[FAIL] Gap konnte nicht gefüllt werden. Überspringe...")
                current_time += 30 

if __name__ == "__main__":
    if len(sys.argv) > 4:
        execute_job(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
