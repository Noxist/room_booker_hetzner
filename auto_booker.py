import sys
import json
import time
import os
import subprocess
from datetime import datetime
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.calendar_sync import CalendarSync
from roombooker.server_logger import ServerLogger

KNOWN_ROOMS_ALL = ["A-204", "A-206", "A-231", "A-233", "A-235", "A-237", "A-241", "D-202", "D-204", "D-206", "D-231", "D-233", "D-235", "D-237", "D-239", "D-243"]

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f: return json.load(f)
    return {}

def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0

def ensure_browsers():
    try:
        print("[SETUP] Prüfe Playwright Browser...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("[SETUP] Browser bereit.")
    except Exception as e:
        print(f"[ERROR] Konnte Browser nicht installieren: {e}")

def get_browser(p, headless=True):
    try:
        return p.chromium.launch(headless=headless)
    except Exception as e:
        if "Executable doesn't exist" in str(e):
            print("\n[ALERT] Browser fehlen! Starte Auto-Installation...")
            ensure_browsers()
            return p.chromium.launch(headless=headless)
        raise e

def scan_rooms(date_str, allowed_rooms=None):
    d_parts = date_str.split(".")
    iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
    target_rooms = allowed_rooms if allowed_rooms else KNOWN_ROOMS_ALL
    rooms_data = {r: [] for r in target_rooms}
    
    with sync_playwright() as p:
        browser = get_browser(p)
        page = browser.new_page()
        print(f"[SCAN] Lade Kalender für {date_str}...")
        try:
            url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(2)
            if "select" in page.url:
                 page.goto("https://raumreservation.ub.unibe.ch/set/1")
                 page.goto(url, wait_until="domcontentloaded")
            
            raw = page.evaluate("""() => Array.from(document.querySelectorAll('rect[data-event-event-value]')).map(el => JSON.parse(el.getAttribute('data-event-event-value')))""")
            count = 0
            for e in raw:
                r = e['roomName']
                if r in rooms_data:
                    rooms_data[r].append({"start_m": t2m(e['start'].split('T')[1][:5]), "end_m": t2m(e['end'].split('T')[1][:5])})
                    count += 1
            print(f"[SCAN] {count} belegte Slots gefunden.")
        except Exception as e: print(f"[ERROR] Scan failed: {e}")
        finally: browser.close()
    return rooms_data

def find_best_chain(rooms_data, start, end, accounts, weights):
    candidates = []
    for room, bookings in rooms_data.items():
        sorted_b = sorted(bookings, key=lambda x: x['start_m'])
        limit = end
        for b in sorted_b:
            if b['end_m'] <= start: continue
            if b['start_m'] <= start: limit = start; break 
            if b['start_m'] > start: limit = min(limit, b['start_m']); break
        
        actual_end = limit 
        duration = actual_end - start
        if duration >= 30: 
            score = duration * weights.get("totalCoveredMin", 0.01)
            candidates.append({"room": room, "start": start, "end": actual_end, "duration": duration, "score": score})
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    if not candidates: return []
    
    best = candidates[0]
    result_chain = [best]
    if best['end'] < end and accounts > 1:
        remainder = find_best_chain(rooms_data, best['end'], end, accounts - 1, weights)
        if remainder: result_chain.extend(remainder)
    return result_chain

def book_chain(chain, accounts_list, date_str):
    print("\n--- BUCHUNGSPROZESS ---")
    successes = []
    with sync_playwright() as p:
        browser = get_browser(p)
        for i, step in enumerate(chain):
            if i >= len(accounts_list): break
            acc = accounts_list[i]
            room = step['room']
            start_t = m2t(step['start'])
            end_t = m2t(step['end'])
            print(f"[BOOK] {start_t}-{end_t} | {room} | {acc.email}")
            
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto("https://raumreservation.ub.unibe.ch/event/add")
                # Login Logik
                if "login" in page.url or "wayf" in page.url or page.locator("#username").is_visible():
                     if "/select" in page.url: page.goto("https://raumreservation.ub.unibe.ch/set/1")
                     if page.locator("#username").is_visible():
                        page.fill("#username", acc.email)
                        page.keyboard.press("Enter")
                        time.sleep(1)
                        if page.locator("#password").is_visible():
                            page.fill("#password", acc.password)
                            page.keyboard.press("Enter")
                        page.wait_for_load_state("networkidle")
            
                if "/event/add" not in page.url: page.goto("https://raumreservation.ub.unibe.ch/event/add")
                
                found = page.evaluate(f"""(rName) => {{
                    const sel = document.querySelector('#event_room');
                    if(!sel) return false;
                    for(let i=0; i<sel.options.length; i++) {{
                        if(sel.options[i].innerText.includes(rName)) {{
                            sel.selectedIndex = i; sel.dispatchEvent(new Event('change')); return true;
                        }}
                    }}
                    return false;
                }}""", room)
                
                if found:
                    time.sleep(0.5)
                    page.fill("#event_startDate", f"{date_str} {start_t}")
                    page.keyboard.press("Enter")
                    dur = step['end'] - step['start']
                    page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
                    page.evaluate("document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))")
                    time.sleep(0.5)
                    page.fill("#event_title", "Lernen")
                    try: page.check('input[name="event[purpose]"][value="Other"]') 
                    except: pass
                    
                    page.click("#event_submit")
                    try:
                        page.wait_for_url(lambda u: "/event/add" not in u, timeout=5000)
                        print(f"[SUCCESS] ✅ {room} gebucht.")
                        d_obj = datetime.strptime(date_str, "%d.%m.%Y").date()
                        successes.append({
                            "start": datetime.combine(d_obj, datetime.strptime(start_t, "%H:%M").time()),
                            "end": datetime.combine(d_obj, datetime.strptime(end_t, "%H:%M").time()),
                            "room": room,
                            "account": acc.email
                        })
                    except: print(f"[FAIL] ❌ {room} nicht bestätigt.")
                else: print(f"[ERROR] Raum {room} nicht gefunden.")
            except Exception as e: print(f"[ERROR] {e}")
            finally: context.close()
        browser.close()
    return successes

def execute_job(date_str, start_time, end_time, category_key, num_accounts):
    data_dir = resolve_data_dir()
    categories = load_json("categories.json")
    weights = load_json("weights.json") 
    accs = load_accounts(data_dir / "settings.json")
    
    cat_data = categories.get(category_key, categories.get("default"))
    target_rooms = cat_data.get("rooms", KNOWN_ROOMS_ALL)
    
    if isinstance(num_accounts, str) and "max" in num_accounts: use_accs = accs
    else:
        try: use_accs = accs[:int(num_accounts)]
        except: use_accs = accs

    print(f"--- ANALYSE: {date_str} ---")
    rooms_data = scan_rooms(date_str, target_rooms)
    chain = find_best_chain(rooms_data, t2m(start_time), t2m(end_time), len(use_accs), weights)
    
    if chain:
        print(f"[PLAN] Strategie: {len(chain)} Abschnitte gefunden.")
        # FIX: Parameter Korrektur hier
        success_list = book_chain(chain, use_accs, date_str)
        
        if success_list:
            try:
                print("\n[SYNC] Google Kalender Update...")
                creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", str(data_dir / "google_credentials.json"))
                cal_id = os.environ.get("GOOGLE_CALENDAR_ID", "")
                if cal_id:
                    syncer = CalendarSync(creds_path, cal_id, ServerLogger())
                    syncer.sync_slots(success_list)
                    print("[SYNC] Fertig.")
                else:
                    print("[WARN] Keine Google Calendar ID gesetzt (Prüfe .env).")
            except Exception as e:
                print(f"[SYNC ERROR] {e}")
        return True
    else:
        print("[RESULT] Keine freien Räume für diesen Zeitraum gefunden.")
        return False

def manual_sync_check():
    print("\n=== MANUAL SYNC ===")
    data_dir = resolve_data_dir()
    cal_id = os.environ.get("GOOGLE_CALENDAR_ID", "")
    if not cal_id:
        print("[ERROR] Keine Google Calendar ID in ENV gefunden (Prüfe .env Datei).")
        return
        
    print(f"[INFO] Verbinde zu Kalender: {cal_id[:15]}...")
    try:
        creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", str(data_dir / "google_credentials.json"))
        syncer = CalendarSync(creds_path, cal_id, ServerLogger())
        print("[SUCCESS] Verbindung erfolgreich hergestellt ✅")
        print("[INFO] Der Sync läuft automatisch nach jeder erfolgreichen Buchung.")
    except Exception as e:
        print(f"[ERROR] Verbindung fehlgeschlagen: {e}")
