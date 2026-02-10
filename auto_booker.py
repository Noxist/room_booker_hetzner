import sys
import json
import time
import os
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.calendar_sync import CalendarSync

ALL_VONROLL_ROOMS = [
    "A-204", "D-204", "A-206", "A-231", "A-233", "A-235", "A-237", "A-241", 
    "D-202", "D-206", "D-231", "D-233", "D-235", "D-237", "D-239", "D-243"
]

CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "3aa0292bb1019576073ee6521bdf7f12f1c795703be4cd02333217a809397b6e@group.calendar.google.com")

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f: return json.load(f)
    return {}

def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0

# --- CORE: TABLE PARSER ---
def parse_reservations(page):
    """
    Liest die Tabelle auf der Seite 'Meine Reservationen' aus.
    Gibt eine Liste von Dictionaries zurueck:
    [{'start': datetime, 'end': datetime, 'room': 'A-231'}, ...]
    """
    reservations = []
    
    # Sicherstellen, dass wir auf der richtigen Seite sind
    if "reservation" not in page.url:
        page.goto("https://raumreservation.ub.unibe.ch/reservation")
        page.wait_for_load_state("networkidle")
    
    # Wir suchen direkt nach den Datenzeilen im Body
    rows = page.locator("tbody tr").all()
    
    if not rows:
        return []

    for row in rows:
        try:
            # Hole den gesamten Text der Zeile fuer Regex-Suche
            # Das ist robuster als einzelne Zellen, da Spalten sich verschieben koennen
            row_text = row.inner_text().replace("\n", " ")
            
            # Regex: DD.MM.YYYY HH:MM - HH:MM
            # Beispiel: 10.02.2026 10:00 - 12:00
            time_match = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", row_text)
            
            # Regex: Raum (A-XXX oder D-XXX)
            room_match = re.search(r"\b([A-D]-\d{3})\b", row_text)
            
            if time_match and room_match:
                d_str, t_start, t_end = time_match.groups()
                room = room_match.group(1)
                
                dt_start = datetime.strptime(f"{d_str} {t_start}", "%d.%m.%Y %H:%M")
                dt_end = datetime.strptime(f"{d_str} {t_end}", "%d.%m.%Y %H:%M")
                
                reservations.append({
                    "start": dt_start,
                    "end": dt_end,
                    "room": room,
                    "raw": row_text
                })
        except Exception:
            pass # Skip bad rows
            
    return reservations

# --- GOOGLE CALENDAR SYNC ---
def sync_to_google(room, date_str, start_time, end_time):
    if not CALENDAR_ID:
        return

    print(f"   [SYNC] Sende an Google Kalender ({CALENDAR_ID})...")
    try:
        data_dir = resolve_data_dir()
        creds_path = data_dir / "google_credentials.json"
        
        if not creds_path.exists():
            print(f"   [ERROR] google_credentials.json fehlt in {data_dir}!")
            return

        dt_start = datetime.strptime(f"{date_str} {start_time}", "%d.%m.%Y %H:%M")
        dt_end = datetime.strptime(f"{date_str} {end_time}", "%d.%m.%Y %H:%M")
        
        slot = {"start": dt_start, "end": dt_end, "room": room}
        
        syncer = CalendarSync(str(creds_path), CALENDAR_ID, None)
        syncer.sync_slots([slot])
        print("   [SYNC] Erfolgreich gespeichert!")
    except Exception as e:
        print(f"   [ERROR] Kalender Sync fehlgeschlagen: {e}")

# --- RESERVATIONS CHECK ---
def check_existing_reservations(page, req_date_str, req_start, req_end):
    """
    Prueft VOR dem Buchen, ob es Konflikte gibt.
    """
    print(f"   [CHECK] Pruefe bestehende Reservationen fuer {req_date_str}...")
    
    # 1. Zur Liste navigieren
    try:
        if "reservation" not in page.url:
            page.goto("https://raumreservation.ub.unibe.ch/reservation")
            page.wait_for_load_state("networkidle")
    except:
        return True # Im Fehlerfall lassen wir es durchgehen

    # 2. Parsen
    existing_res = parse_reservations(page)
    
    if not existing_res:
        print("   [CHECK] Liste leer. Bahn frei.")
        return True

    # 3. Vergleichen
    req_start_m = t2m(req_start)
    req_end_m = t2m(req_end)
    
    for res in existing_res:
        # Datum Check
        res_date_str = res["start"].strftime("%d.%m.%Y")
        if res_date_str != req_date_str:
            continue
            
        # Zeit Check (Minuten berechnen)
        r_start_m = res["start"].hour * 60 + res["start"].minute
        r_end_m = res["end"].hour * 60 + res["end"].minute
        
        # Logik: (StartA < EndB) und (EndA > StartB)
        if req_start_m < r_end_m and req_end_m > r_start_m:
            print(f"   [ABORT] KONFLIKT GEFUNDEN!")
            print(f"           Existierend: {res_date_str} {m2t(r_start_m)}-{m2t(r_end_m)} in {res['room']}")
            return False # Blockieren!
            
    print("   [CHECK] OK - Keine Ueberschneidungen.")
    return True

# --- NAVIGATION & LOGIN ---
def handle_eduid_login(page, email, password):
    print(f"[DEBUG] edu-ID Login Maske fuer {email}...")
    try:
        page.wait_for_selector("input", timeout=5000)
        
        if page.get_by_test_id("login-username-field").is_visible():
             page.get_by_test_id("login-username-field").fill(email)
             page.get_by_test_id("login-username-field").press("Enter")
        elif page.locator("#username").is_visible():
             page.fill("#username", email)
             page.keyboard.press("Enter")
        
        time.sleep(1)
        if page.get_by_test_id("button-submit").is_visible():
            page.get_by_test_id("button-submit").click()

        time.sleep(2)
        if page.get_by_test_id("login-password-field").is_visible():
            page.get_by_test_id("login-password-field").fill(password)
            page.get_by_test_id("login-password-field").press("Enter")
        elif page.locator("input[type='password']").is_visible():
            page.locator("input[type='password']").fill(password)
            page.keyboard.press("Enter")
        
        time.sleep(2)
        if page.get_by_test_id("button-proceed").is_visible():
            page.get_by_test_id("button-proceed").click()
        
        page.wait_for_load_state("networkidle", timeout=30000)
        return True
    except:
        return False

def ensure_location_and_link(page):
    # Standorte Button (falls Dropdown)
    try:
        if page.get_by_role("button", name="Standorte").count() > 0:
             if page.get_by_role("button", name="Standorte").first.is_visible():
                 page.get_by_role("button", name="Standorte").first.click()
                 time.sleep(0.5)
    except: pass

    # Link vonRoll (Strict Mode Safe)
    try:
        link = page.get_by_role("link", name="Bibliothek vonRoll").first
        if link.is_visible():
            link.click()
            page.wait_for_load_state("networkidle")
            return True
    except: pass
    
    if "set/1" not in page.url and "event" in page.url:
        page.goto("https://raumreservation.ub.unibe.ch/set/1")
    return True

def perform_login(page, email, password):
    target = "https://raumreservation.ub.unibe.ch/event/add"
    if page.url != target:
        page.goto(target)
        page.wait_for_load_state("networkidle")

    for _ in range(3):
        if "eduid" in page.url or "login" in page.url:
            handle_eduid_login(page, email, password)
        
        if "raumreservation.ub.unibe.ch" in page.url and "login" not in page.url:
            ensure_location_and_link(page)
            return True
            
        time.sleep(2)
    return False

def nav_to_form(page):
    if "event/add" in page.url:
        try: 
            page.wait_for_selector("#event_room", timeout=3000)
            if page.locator("#event_room").is_visible(): return True
        except: pass

    print("   [NAV] Suche Formular...")
    try:
        # Toggle Navigation (Mobile/Small Screen)
        if page.get_by_role("button", name="Toggle navigation").is_visible():
             page.get_by_role("button", name="Toggle navigation").click()
             time.sleep(0.5)

        if page.get_by_role("link", name="Neue Reservation").count() > 0:
            page.get_by_role("link", name="Neue Reservation").first.click()
        else:
            page.goto("https://raumreservation.ub.unibe.ch/event/add")
        
        page.wait_for_load_state("networkidle")
        return True
    except:
        return False

# --- MANUAL SYNC FUNCTION ---
def sync_reservations_to_google(accounts):
    print("--- STARTE MANUELLEN SYNC ---")
    data_dir = resolve_data_dir()
    creds_path = data_dir / "google_credentials.json"
    
    if not creds_path.exists():
        print(f"[ERROR] google_credentials.json fehlt in {data_dir}")
        return

    try:
        syncer = CalendarSync(str(creds_path), CALENDAR_ID, None)
    except Exception as e:
        print(f"[ERROR] Init Fehler: {e}")
        return

    all_slots = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        for acc in accounts:
            print(f"[SYNC] Lade Account: {acc.email}...")
            try:
                # 1. Login
                if not perform_login(page, acc.email, acc.password):
                    print(f"[WARN] Login fehlgeschlagen fuer {acc.email}")
                    continue
                
                # 2. Parsen
                reservations = parse_reservations(page)
                print(f"   -> {len(reservations)} Eintraege gefunden.")
                
                for res in reservations:
                    res["user"] = acc.email
                    all_slots.append(res)
                    
            except Exception as e:
                print(f"[ERROR] Fehler: {e}")
            
            # Logout Cleanup
            context.clear_cookies()
        
        browser.close()

    if all_slots:
        print(f"[SYNC] Sende {len(all_slots)} Termine an Google...")
        try:
            syncer.sync_slots(all_slots)
            print("[SUCCESS] Sync fertig.")
        except Exception as e:
            print(f"[ERROR] API Fehler: {e}")
    else:
        print("[INFO] Keine Reservationen gefunden.")


# --- BOOKING LOGIC ---
def scan_rooms(date_str):
    d_parts = date_str.split(".")
    iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
    rooms_data = {r: [] for r in ALL_VONROLL_ROOMS}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        print(f"[SCAN] Kalender Scan {date_str}...")
        try:
            page.goto(f"https://raumreservation.ub.unibe.ch/event?day={iso_date}")
            ensure_location_and_link(page)
            try: page.wait_for_selector('rect[data-event-event-value]', timeout=5000)
            except: pass
            raw = page.evaluate("""() => Array.from(document.querySelectorAll('rect[data-event-event-value]')).map(el => JSON.parse(el.getAttribute('data-event-event-value')))""")
            print(f"[SCAN] {len(raw)} Belegungen gefunden.")
            for e in raw:
                r = e['roomName']
                if r in rooms_data:
                    rooms_data[r].append({
                        "start_m": t2m(e['start'].split('T')[1][:5]), 
                        "end_m": t2m(e['end'].split('T')[1][:5])
                    })
        except Exception as e: print(f"[ERROR] Scan failed: {e}")
        finally: browser.close()
    return rooms_data

def find_best_chain(rooms_data, start, end, target_category_rooms=None):
    candidates = []
    room_pool = target_category_rooms if target_category_rooms else list(rooms_data.keys())
    print(f"[CHECK] Suche in {len(room_pool)} Raeumen...")
    for room in room_pool:
        bookings = rooms_data.get(room, [])
        if is_slot_free(bookings, start, end):
            candidates.append(room)
    if candidates:
        print(f"[RESULT] {len(candidates)} freie Raeume: {candidates}")
        return candidates[0]
    return None

def is_slot_free(bookings, req_start, req_end):
    if not bookings: return True
    for b in bookings:
        if req_start < b['end_m'] and req_end > b['start_m']:
            return False
    return True

def book_room(room, start, end, accounts_list, date_str):
    acc = accounts_list[0]
    start_t, end_t = m2t(start), m2t(end)
    duration_min = end - start
    
    print(f"\n--- BUCHE RAUM {room} ---")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        try:
            # 1. Login
            if not perform_login(page, acc.email, acc.password):
                print("   [ERROR] Login fehlgeschlagen.")
                return False

            # 2. DOPPELBUCHUNGS-CHECK
            if not check_existing_reservations(page, date_str, start_t, end_t):
                # Bereits gebucht -> Erfolgreich, weil Ziel erreicht
                return True

            # 3. Zum Formular
            if not nav_to_form(page):
                print("   [ERROR] Formular nicht gefunden.")
                return False

            # 4. Ausfuellen
            print("   [DEBUG] Fuelle Formular aus...")
            try: page.wait_for_selector("#event_room", state="visible", timeout=10000)
            except:
                print(f"   [ERROR] Dropdown fehlt.")
                return False

            print(f"   [DEBUG] Waehle {room}...")
            found = page.evaluate(f"""(rName) => {{
                const sel = document.querySelector('#event_room');
                for(let i=0; i<sel.options.length; i++) {{
                    if(sel.options[i].innerText.includes(rName)) {{
                        sel.selectedIndex = i; sel.dispatchEvent(new Event('change')); return true;
                    }}
                }}
                return false;
            }}""", room)
            
            if not found:
                print(f"   [ERROR] {room} nicht im Dropdown.")
                return False
            
            page.fill("#event_startDate", f"{date_str} {start_t}")
            page.keyboard.press("Enter")
            page.fill("#event_duration", str(duration_min))
            page.keyboard.press("Enter")
            page.fill("#event_title", "Lernen")
            
            try:
                if page.get_by_role("radio", name="Anderes").is_visible():
                    page.get_by_role("radio", name="Anderes").check()
                else:
                    page.check('input[name="event[purpose]"][value="Other"]')
            except: pass
            
            print("   [DEBUG] Speichere...")
            page.click("#event_submit")
            
            time.sleep(3)
            if "event/add" in page.url:
                # FEHLER ANALYSE
                body_text = page.inner_text("body")
                if "Zu dem gegebenen Zeitpunkt" in body_text:
                    print("   [ERROR] GRUND: KOLLISION (Raum belegt).")
                elif "Reservationen können hö" in body_text:
                    print("   [ERROR] GRUND: REGELVERSTOSS (Zeit/Dauer).")
                else:
                    print("   [ERROR] Speichern fehlgeschlagen.")
                return False
            else:
                print(f"[SUCCESS] {room} gebucht!")
                sync_to_google(room, date_str, start_t, end_t)
                return True

        except Exception as e:
            print(f"   [CRASH] {e}")
            return False
        finally:
            browser.close()

def execute_job(date_str, start_time, end_time, category_key, num_accounts):
    data_dir = resolve_data_dir()
    categories = load_json("categories.json")
    accs = load_accounts(data_dir / "settings.json")
    cat_data = categories.get(category_key, {})
    target_rooms = cat_data.get("rooms", [])
    
    print(f"--- EXEC: {date_str} ---")
    rooms_data = scan_rooms(date_str)
    start_m, end_m = t2m(start_time), t2m(end_time)
    
    best_room = find_best_chain(rooms_data, start_m, end_m, target_rooms)
    if not best_room:
        print(f"[INFO] Kategorie '{category_key}' voll. Fallback auf ALLE...")
        best_room = find_best_chain(rooms_data, start_m, end_m, ALL_VONROLL_ROOMS)
        
    if best_room:
        return book_room(best_room, start_m, end_m, accs, date_str)
    else:
        print("ALLES VOLL.")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sync_only":
        accs = load_accounts(resolve_data_dir() / "settings.json")
        sync_reservations_to_google(accs)
    elif len(sys.argv) > 4:
        execute_job(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
