import json
import time
import sys
import itertools
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.config import URLS

# --- KONFIGURATION ---
TARGET_START = "08:00"
TARGET_END = "20:00"
PREFERRED_ROOMS = ["D-204", "A-204", "A-241", "D-239", "D-231", "A-231", "D-202", "D-235"]

def t2m(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def m2t(mins):
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

def get_free_intervals(room_bookings, req_start_m, req_end_m):
    sorted_bookings = sorted(room_bookings, key=lambda x: x['start_m'])
    free_slots = []
    cursor = req_start_m
    for b in sorted_bookings:
        if b['end_m'] <= cursor: continue
        if b['start_m'] > cursor:
            gap_end = min(b['start_m'], req_end_m)
            if gap_end > cursor:
                free_slots.append((cursor, gap_end))
            cursor = b['end_m']
        else:
            cursor = max(cursor, b['end_m'])
        if cursor >= req_end_m: break
    if cursor < req_end_m:
        free_slots.append((cursor, req_end_m))
    return free_slots

def solve_schedule(rooms_data, num_accounts, req_start, req_end):
    print(f"🧮 Suche optimalen Plan für {num_accounts} Accounts ({m2t(req_start)} - {m2t(req_end)})...")
    
    # Alle verfügbaren Slots sammeln
    # Struktur: list of (room, start, end, duration)
    all_slots = []
    for r in PREFERRED_ROOMS:
        intervals = get_free_intervals(rooms_data.get(r, []), req_start, req_end)
        for s, e in intervals:
            # Nur Slots berücksichtigen, die mindestens 30 min lang sind
            if (e - s) >= 30:
                all_slots.append({'room': r, 'start': s, 'end': e, 'len': e-s})

    # --- STRATEGIE 1: 1 Raum (Holistic) ---
    print("   Prüfe 1 Raum...")
    for s in all_slots:
        if s['start'] <= req_start and s['end'] >= req_end:
            return [{
                "start": m2t(req_start), "end": m2t(req_end), 
                "room": s['room'], "info": "Perfekt (Ganzer Tag)"
            }]

    if num_accounts < 2:
        return find_longest_partial(all_slots)

    # --- STRATEGIE 2: 2 Räume (Split) ---
    print("   Prüfe 2 Räume (Split)...")
    best_2_sol = None
    max_score_2 = 0 # Score = Abgedeckte Zeit + Bonus für lange Blöcke

    # Wir suchen 2 Slots (A, B), die sich berühren oder überlappen und den Zeitraum füllen
    # Iteriere alle Paare
    import itertools
    for s1, s2 in itertools.permutations(all_slots, 2):
        # Bedingungen:
        # s1 muss am Anfang starten (oder früher)
        if s1['start'] > req_start: continue
        # s2 muss am Ende aufhören (oder später)
        if s2['end'] < req_end: continue
        
        # Sie müssen sich treffen: s1.end >= s2.start
        if s1['end'] < s2['start']: continue
        
        # Gültiger Split gefunden!
        # Schnittpunkt bestimmen (wir wechseln so spät wie möglich oder so früh wie möglich?)
        # Wir wollen Kohärenz: Der längere Block soll maximiert werden.
        
        # Möglicher Wechselbereich: [s2.start, s1.end]
        # Wir testen den Wechselpunkt, der die max. Blocklänge erzeugt
        switch_min = max(s2['start'], req_start)
        switch_max = min(s1['end'], req_end)
        
        # Finde besten switch im Bereich
        # Einfache Heuristik: Nimm die Mitte oder einen der Ränder, was den längeren Teilblock maximiert
        len_a_opts = [switch_min - req_start, switch_max - req_start]
        best_switch = switch_min if len_a_opts[0] > len_a_opts[1] else switch_max
        
        # Wenn switch == req_start oder req_end, ist es eigentlich eine 1-Raum Lösung (schon geprüft)
        if best_switch <= req_start or best_switch >= req_end: continue
        
        len_a = best_switch - req_start
        len_b = req_end - best_switch
        score = min(len_a, len_b) # Wir maximieren den KÜRZEREN Teil -> gleichmäßige Verteilung? 
        # Nein, User will "möglichst lange Kohärenz". Also max(len_a, len_b)
        coherence_score = max(len_a, len_b)
        
        if coherence_score > max_score_2:
            max_score_2 = coherence_score
            best_2_sol = [
                {"start": m2t(req_start), "end": m2t(best_switch), "room": s1['room']},
                {"start": m2t(best_switch), "end": m2t(req_end), "room": s2['room']}
            ]
            
    if best_2_sol:
        # Wir geben die 2-Raum Lösung zurück, es sei denn wir finden mit 3 Räumen was deutlich besseres (unwahrscheinlich bei voller Abdeckung)
        # Aber wir prüfen 3 Räume nur, wenn 2 Räume NICHT den ganzen Tag abdecken konnten?
        # Nein, hier haben wir 100% Abdeckung gefunden. 2 Splits sind immer besser als 3.
        return best_2_sol


    if num_accounts < 3:
        # Falls keine volle Abdeckung mit 2, suche beste Teilabdeckung
        return find_longest_partial(all_slots)

    # --- STRATEGIE 3: 3 Räume (Brückenschlag) ---
    print("   Prüfe 3 Räume (Triple Split)...")
    best_3_sol = None
    max_score_3 = 0
    
    # Das wird rechenintensiver (O(N^3)), aber bei N < 50 Slots kein Problem.
    # Wir suchen s1 (Start), s2 (Mitte), s3 (Ende)
    # Optimierung: s1 muss Start abdecken, s3 muss Ende abdecken.
    starts = [s for s in all_slots if s['start'] <= req_start]
    ends = [s for s in all_slots if s['end'] >= req_end]
    mids = all_slots # Alle können Mitte sein
    
    for s1 in starts:
        for s3 in ends:
            # Wenn s1 und s3 sich schon treffen, ist es ein 2-Split (schon geprüft)
            if s1['end'] >= s3['start']: continue
            
            # Wir suchen ein s2, das die Lücke zwischen s1 und s3 füllt
            gap_start = s1['end']
            gap_end = s3['start']
            
            # s2 muss [gap_start, gap_end] abdecken
            # also s2.start <= gap_start und s2.end >= gap_end
            valid_mids = [m for m in mids if m['start'] <= gap_start and m['end'] >= gap_end]
            
            for s2 in valid_mids:
                # Valid Triple found!
                # Wechselpunkte: gap_start und gap_end
                # Kohärenz-Score: Max Blocklänge
                l1 = gap_start - req_start
                l2 = gap_end - gap_start
                l3 = req_end - gap_end
                score = max(l1, l2, l3)
                
                if score > max_score_3:
                    max_score_3 = score
                    best_3_sol = [
                        {"start": m2t(req_start), "end": m2t(gap_start), "room": s1['room']},
                        {"start": m2t(gap_start), "end": m2t(gap_end), "room": s2['room']},
                        {"start": m2t(gap_end), "end": m2t(req_end), "room": s3['room']}
                    ]
                    
    if best_3_sol:
        return best_3_sol

    return find_longest_partial(all_slots)

def find_longest_partial(all_slots):
    print("   -> Fallback: Beste Teil-Abdeckung...")
    if not all_slots: return None
    # Sortiere nach Länge
    best = max(all_slots, key=lambda x: x['len'])
    # Umwandeln in Output Format
    # Wir clampen den Slot auf unseren Zielbereich, falls er drüber hinaus geht
    # (Aber wir wollen ja den User informieren, wie lange er bleiben KÖNNTE)
    return [{
        "start": m2t(best['start']), 
        "end": m2t(best['end']), 
        "room": best['room'], 
        "info": f"Teilweise ({best['len']//60}h)"
    }]

def extract_bookings_from_page(page):
    print("🔍 Extrahiere Buchungsdaten...")
    bookings = page.evaluate("""() => {
        const elements = document.querySelectorAll('rect[data-event-event-value]');
        const results = [];
        elements.forEach(el => {
            try {
                const data = JSON.parse(el.getAttribute('data-event-event-value'));
                if (data.start && data.end && data.roomName) {
                    results.push({
                        room: data.roomName,
                        start: data.start.split('T')[1].substring(0, 5),
                        end: data.end.split('T')[1].substring(0, 5)
                    });
                }
            } catch (e) {}
        });
        return results;
    }""")
    return bookings

def run_math_scan(target_date_str):
    print(f"--- 🧮 DYNAMISCHER SCAN v2 FÜR {target_date_str} ---")
    data_dir = resolve_data_dir()
    accs = load_accounts(data_dir / "settings.json")
    if not accs: 
        print("❌ Keine Accounts gefunden.")
        return
    
    num_accounts = len(accs)
    print(f"ℹ️ Verfügbare Accounts: {num_accounts} -> Max {num_accounts} Splits möglich.")

    session_files = list(data_dir.glob("session_*.json"))
    session_path = session_files[0] if session_files else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(session_path)) if session_path else browser.new_context()
        page = context.new_page()

        try:
            d_parts = target_date_str.split(".")
            iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
            target_url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            
            print(f"Navigiere zu: {target_url}")
            page.goto(target_url)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            if "/select" in page.url:
                page.goto("https://raumreservation.ub.unibe.ch/set/1")
                time.sleep(1)
                page.goto(target_url)
                time.sleep(2)

            if "login" in page.url or "wayf" in page.url:
                print("⚠️ Login nötig...")
                if page.locator("#username").is_visible():
                    page.fill("#username", accs[0].email)
                    page.keyboard.press("Enter")
                    time.sleep(2)
                    page.fill("#password", accs[0].password)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("networkidle")
                    new_session = data_dir / f"session_{accs[0].email.replace('@','_')}.json"
                    context.storage_state(path=str(new_session))
                    page.goto(target_url)
                    time.sleep(3)

            try:
                page.wait_for_selector("rect[data-event-event-value]", timeout=5000)
            except:
                print("ℹ️ Keine Buchungen sichtbar.")

            raw_bookings = extract_bookings_from_page(page)
            
            # Daten aufbereiten
            rooms_data = {r: [] for r in PREFERRED_ROOMS}
            for b in raw_bookings:
                if b['room'] in rooms_data:
                    b['start_m'] = t2m(b['start'])
                    b['end_m'] = t2m(b['end'])
                    rooms_data[b['room']].append(b)
            
        except Exception as e:
            print(f"❌ Browser Fehler: {e}")
            browser.close()
            return

        browser.close()

        # PLAN BERECHNEN
        req_start = t2m(TARGET_START)
        req_end = t2m(TARGET_END)
        
        plan = solve_schedule(rooms_data, num_accounts, req_start, req_end)
        
        if plan:
            print("\n✅ OPTIMALER PLAN:")
            print(json.dumps(plan, indent=2))
        else:
            print("❌ Kein Plan gefunden.")

if __name__ == "__main__":
    import sys
    import datetime
    target = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    if len(sys.argv) > 1:
        target = sys.argv[1]
    run_math_scan(target)
