import json
import time
import sys
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.config import URLS

# --- KONFIGURATION ---
TARGET_START = "08:00"
TARGET_END = "20:00"
PREFERRED_ROOMS = ["D-204", "A-204", "A-241", "D-239", "D-231", "A-231", "D-202"]

def time_to_minutes(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def minutes_to_time(mins):
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

def get_free_intervals(room_bookings, req_start_m, req_end_m):
    """
    Berechnet die FREIEN Zeiten basierend auf den Buchungen.
    """
    # Sortiere Buchungen nach Startzeit
    sorted_bookings = sorted(room_bookings, key=lambda x: x['start_m'])
    
    free_slots = []
    cursor = req_start_m
    
    for b in sorted_bookings:
        # Buchung endet, bevor unser Zeitraum beginnt -> ignorieren
        if b['end_m'] <= cursor:
            continue
        
        # Buchung beginnt später als der Cursor -> Lücke gefunden!
        if b['start_m'] > cursor:
            gap_end = min(b['start_m'], req_end_m)
            if gap_end > cursor:
                free_slots.append((cursor, gap_end))
            cursor = b['end_m'] # Cursor ans Ende der Buchung setzen
        else:
            # Buchung überlappt den Cursor -> Cursor ans Ende der Buchung schieben
            cursor = max(cursor, b['end_m'])
            
        if cursor >= req_end_m:
            break
            
    # Lücke am Ende prüfen (nach der letzten Buchung bis 20:00)
    if cursor < req_end_m:
        free_slots.append((cursor, req_end_m))
        
    return free_slots

def calculate_best_slot(all_bookings):
    print("🧮 Starte mathematische Optimierung...")
    
    req_start = time_to_minutes(TARGET_START)
    req_end = time_to_minutes(TARGET_END)
    
    # Datenvorbereitung: Buchungen den Räumen zuordnen
    rooms_data = {r: [] for r in PREFERRED_ROOMS}
    for b in all_bookings:
        if b['room'] in rooms_data:
            b['start_m'] = time_to_minutes(b['start'])
            b['end_m'] = time_to_minutes(b['end'])
            rooms_data[b['room']].append(b)

    # ---------------------------------------------------------
    # STRATEGIE 1: HOLISTIC (Der Heilige Gral)
    # ---------------------------------------------------------
    print("   Prüfe Strategie 1: Ganzer Tag im selben Raum...")
    for room in PREFERRED_ROOMS:
        free_intervals = get_free_intervals(rooms_data[room], req_start, req_end)
        # Wenn genau ein Intervall existiert und es die volle Länge hat
        for start, end in free_intervals:
            if start == req_start and end == req_end:
                return [{
                    "start": TARGET_START,
                    "end": TARGET_END,
                    "room": room,
                    "info": "Perfekt (Ganzer Tag)"
                }]

    # ---------------------------------------------------------
    # STRATEGIE 2: SMART SPLIT (Max Kohärenz)
    # ---------------------------------------------------------
    print("   Prüfe Strategie 2: Split mit maximaler Sitzdauer...")
    best_split = None
    max_continuous_block = 0 # Wir wollen den längsten Block maximieren
    
    # Wir prüfen alle 30min als möglichen Wechselpunkt
    step = 30
    for split_point in range(req_start + step, req_end, step):
        
        room_a = None # Raum vor dem Wechsel
        room_b = None # Raum nach dem Wechsel
        
        # Finde Raum A (Start -> Wechsel)
        for r in PREFERRED_ROOMS:
            slots = get_free_intervals(rooms_data[r], req_start, split_point)
            if any(s == req_start and e == split_point for s, e in slots):
                room_a = r
                break # Nimm den ersten aus der Prio-Liste
        
        if not room_a: continue

        # Finde Raum B (Wechsel -> Ende)
        for r in PREFERRED_ROOMS:
            if r == room_a: continue # Wäre sonst Holistic
            slots = get_free_intervals(rooms_data[r], split_point, req_end)
            if any(s == split_point and e == req_end for s, e in slots):
                room_b = r
                break # Nimm den ersten aus der Prio-Liste
        
        if room_a and room_b:
            # Berechne wie "gut" dieser Split ist
            len_a = split_point - req_start
            len_b = req_end - split_point
            longest_part = max(len_a, len_b)
            
            # Wir wollen den Split, der uns den längsten zusammenhängenden Block gibt
            if longest_part > max_continuous_block:
                max_continuous_block = longest_part
                best_split = [
                    {"start": TARGET_START, "end": minutes_to_time(split_point), "room": room_a},
                    {"start": minutes_to_time(split_point), "end": TARGET_END, "room": room_b, "info": f"Split (Wechsel um {minutes_to_time(split_point)})"}
                ]

    if best_split:
        return best_split

    # ---------------------------------------------------------
    # STRATEGIE 3: LONGEST PARTIAL (Notlösung)
    # ---------------------------------------------------------
    print("   Prüfe Strategie 3: Längster verfügbarer Teil-Block...")
    best_partial = None
    max_duration = 0
    
    for room in PREFERRED_ROOMS:
        slots = get_free_intervals(rooms_data[room], req_start, req_end)
        for start, end in slots:
            duration = end - start
            if duration > max_duration:
                max_duration = duration
                best_partial = [{
                    "start": minutes_to_time(start),
                    "end": minutes_to_time(end),
                    "room": room,
                    "info": f"Teilweise ({duration//60}h)"
                }]
    
    # Nur zurückgeben wenn > 2 Stunden, sonst lohnt Anreise nicht
    if best_partial and max_duration >= 120:
        return best_partial

    return None

def extract_bookings_from_page(page):
    print("🔍 Scanne HTML nach SVG-Daten...")
    # Das ist der entscheidende Teil: Wir lesen das data-Attribut aus
    bookings = page.evaluate("""() => {
        const elements = document.querySelectorAll('rect[data-event-event-value]');
        const results = [];
        elements.forEach(el => {
            try {
                const raw = el.getAttribute('data-event-event-value');
                const data = JSON.parse(raw);
                if (data.start && data.end && data.roomName) {
                    results.push({
                        room: data.roomName,
                        // ISO String Parsen (2026-02-05T08:00:00+01:00)
                        start: data.start.split('T')[1].substring(0, 5),
                        end: data.end.split('T')[1].substring(0, 5)
                    });
                }
            } catch (e) { }
        });
        return results;
    }""")
    
    # Nur unsere Räume behalten
    relevant = [b for b in bookings if b['room'] in PREFERRED_ROOMS]
    print(f"✅ {len(relevant)} relevante Buchungen gefunden.")
    return relevant

def run_math_scan(target_date_str):
    print(f"--- 📊 SMART SCAN FÜR {target_date_str} ---")
    data_dir = resolve_data_dir()
    accs = load_accounts(data_dir / "settings.json")
    if not accs: return

    # Session laden um Login zu sparen
    session_files = list(data_dir.glob("session_*.json"))
    session_path = session_files[0] if session_files else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(session_path)) if session_path else browser.new_context()
        page = context.new_page()

        try:
            # Datum URL bauen
            d_parts = target_date_str.split(".")
            iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
            target_url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            
            print(f"Navigiere zu: {target_url}")
            page.goto(target_url)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            # Standort 'vonRoll' erzwingen
            if "/select" in page.url or "Standort" in page.title():
                print("ℹ️ Setze Standort auf vonRoll...")
                page.goto("https://raumreservation.ub.unibe.ch/set/1")
                time.sleep(1)
                page.goto(target_url)
                time.sleep(2)

            # Login Check
            if "login" in page.url or "wayf" in page.url:
                print("⚠️ Login nötig...")
                if page.locator("#username").is_visible():
                    page.fill("#username", accs[0].email)
                    page.keyboard.press("Enter")
                    time.sleep(2)
                    page.fill("#password", accs[0].password)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("networkidle")
                    # Session speichern
                    new_session = data_dir / f"session_{accs[0].email.replace('@','_')}.json"
                    context.storage_state(path=str(new_session))
                    page.goto(target_url)
                    time.sleep(3)

            # Warten bis die SVG-Elemente da sind
            try:
                page.wait_for_selector("rect[data-event-event-value]", timeout=8000)
            except:
                print("ℹ️ Keine Buchungen im DOM gefunden (Vielleicht alles frei?).")

            # DATEN EXTRAHIEREN
            bookings = extract_bookings_from_page(page)
            
        except Exception as e:
            print(f"❌ Browser Fehler: {e}")
            browser.close()
            return

        browser.close()

        # BERECHNEN
        plan = calculate_best_slot(bookings)
        
        if plan:
            print("\n✅ GEFUNDENER OPTIMAL-PLAN:")
            print(json.dumps(plan, indent=2))
        else:
            print("❌ Kein passender Slot gefunden.")

if __name__ == "__main__":
    import sys
    import datetime
    target = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    if len(sys.argv) > 1:
        target = sys.argv[1]
    run_math_scan(target)
