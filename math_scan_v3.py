import json
import time
import sys
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.config import URLS

# --- KONFIGURATION: FAVORITEN ---
# Diese Räume werden bevorzugt, aber andere werden genommen, wenn sie besser passen (weniger Wechsel).
PREFERRED_ROOMS = ["D-204", "A-204", "A-241", "D-239", "D-231", "A-231", "D-202", "D-235"]

# Standardwerte, falls keine Argumente kommen
DEFAULT_START = "08:00"
DEFAULT_END = "20:00"

def parse_arguments(args):
    """
    Parst Argumente wie: "12.02.2026", "10:00-18:00", "/x5"
    """
    config = {
        "date": None,
        "start": DEFAULT_START,
        "end": DEFAULT_END,
        "accounts_override": None
    }
    
    # Datum finden (DD.MM.YYYY)
    for arg in args:
        if re.match(r"\d{2}\.\d{2}\.\d{4}", arg):
            config["date"] = arg
    
    # Zeit finden (HH:MM-HH:MM)
    for arg in args:
        match = re.match(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", arg)
        if match:
            config["start"] = match.group(1).zfill(5) # 8:00 -> 08:00
            config["end"] = match.group(2).zfill(5)
            
    # Account Override finden (/xN)
    for arg in args:
        match = re.match(r"/x(\d+)", arg)
        if match:
            config["accounts_override"] = int(match.group(1))
            
    return config

def t2m(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def m2t(mins):
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

def get_free_intervals(room_bookings, window_start, window_end):
    """Gibt freie Slots innerhalb des Fensters zurück."""
    sorted_bookings = sorted(room_bookings, key=lambda x: x['start_m'])
    free_slots = []
    cursor = window_start
    
    for b in sorted_bookings:
        if b['end_m'] <= cursor: continue
        if b['start_m'] > cursor:
            gap_end = min(b['start_m'], window_end)
            if gap_end > cursor:
                free_slots.append((cursor, gap_end))
            cursor = b['end_m']
        else:
            cursor = max(cursor, b['end_m'])
        if cursor >= window_end: break
            
    if cursor < window_end:
        free_slots.append((cursor, window_end))
    return free_slots

def solve_schedule(all_rooms_data, num_accounts, req_start, req_end):
    # 1. Kapazität berechnen
    # Pro Account = 4 Stunden (240 min)
    max_minutes_capacity = num_accounts * 240
    
    req_duration = req_end - req_start
    # Unser Ziel: Entweder die volle Zeit oder das Maximum was die Accounts hergeben
    target_duration = min(req_duration, max_minutes_capacity)
    
    print(f"🧮 Analyse:")
    print(f"   - Accounts: {num_accounts} (Max. Kapazität: {max_minutes_capacity/60:.1f}h)")
    print(f"   - Zielzeit: {m2t(req_start)} - {m2t(req_end)} ({req_duration/60:.1f}h)")
    print(f"   - Zu verplanen: {target_duration/60:.1f}h (Optimum)")
    print(f"   - Strategie: Minimale Wechsel > Favoriten-Status")

    all_solutions = []

    # --- SCHRITT A: ALLE RÄUME SCANNEN (Auch Nicht-Favoriten) ---
    # Wir suchen erst nach EINEM Raum, der die Target-Duration erfüllt.
    
    for room_name, bookings in all_rooms_data.items():
        is_fav = room_name in PREFERRED_ROOMS
        intervals = get_free_intervals(bookings, req_start, req_end)
        
        for s, e in intervals:
            duration = e - s
            # Wir brauchen nur Blöcke die groß genug sind (z.B. >= target_duration)
            # Wenn target_duration < req_duration ist (wegen Account limit),
            # dann suchen wir den Block, der target_duration erfüllt.
            
            if duration >= target_duration:
                # Wir haben einen Raum gefunden!
                # Wir schneiden den Slot zurecht, damit er genau target_duration lang ist (Start priorisiert)
                # Oder wir nehmen den ganzen Slot? Der User will "möglichst lange".
                # Aber wir KÖNNEN technisch nicht mehr buchen als target_duration.
                
                # Bestimmung des effektiven Slots (wir nehmen den Anfang des freien Bereichs)
                eff_end = min(e, s + target_duration)
                
                score = 1000 # Basis Score für 1 Raum (Kein Wechsel!)
                if is_fav: score += 100 # Bonus für Favorit
                
                all_solutions.append({
                    "type": "Single",
                    "score": score,
                    "plan": [{
                        "start": m2t(s), "end": m2t(eff_end), 
                        "room": room_name, 
                        "info": f"Einzelraum ({'Favorit' if is_fav else 'Alternativ'})"
                    }]
                })

    # Wenn wir Single-Room Lösungen haben, nehmen wir die beste
    if all_solutions:
        best = max(all_solutions, key=lambda x: x['score'])
        print(f"   -> Lösung gefunden! (Score: {best['score']})")
        return best['plan']

    # --- SCHRITT B: SPLITS (Nur wenn nötig und Accounts >= 2) ---
    if num_accounts < 2:
        print("   -> Keine Einzelraum-Lösung und nur 1 Account. Suche längsten Teil-Slot.")
        # Suche einfach den längsten verfügbaren Slot über alle Räume
        longest_slot = None
        max_len = 0
        for r, bookings in all_rooms_data.items():
            intervals = get_free_intervals(bookings, req_start, req_end)
            for s, e in intervals:
                if (e-s) > max_len:
                    max_len = e-s
                    longest_slot = (r, s, e)
        
        if longest_slot:
            # Begrenzen auf Account-Limit (240 min)
            eff_len = min(max_len, 240)
            return [{
                "start": m2t(longest_slot[1]), "end": m2t(longest_slot[1]+eff_len),
                "room": longest_slot[0], "info": f"Teilweise (Max möglich mit 1 Acc)"
            }]
        return None

    print("   -> Kein Einzelraum für volle Zeit. Prüfe Splits...")
    
    # Wir suchen 2 Räume, die zusammen die target_duration ergeben.
    # Hier beschränken wir uns der Performance wegen auf Favoriten + bekannte gute Räume?
    # Nein, wir nehmen alle, aber sortieren Favoriten zuerst.
    
    candidate_rooms = [r for r in all_rooms_data.keys()]
    # Sortieren: Favoriten nach vorne
    candidate_rooms.sort(key=lambda x: x not in PREFERRED_ROOMS)
    
    # Wir nehmen nur die Top 15 Räume für die Split-Berechnung (Performance)
    top_candidates = candidate_rooms[:15]

    best_split = None
    max_continuous = 0

    # Wir suchen einen Wechselpunkt innerhalb der Zeit
    # req_start ... req_end. Wir wollen total target_duration abdecken.
    # Das ist komplex wenn target_duration < req_end - req_start.
    # Vereinfachung: Wir versuchen die Lücken im Zeitstrahl zu füllen.
    
    # Wir iterieren Wechselpunkte
    step = 30
    # Wir suchen im Bereich [req_start, req_end]
    for split in range(req_start + step, req_end, step):
        # Wenn wir Account-Limits haben, darf der erste Block max 4h (240m) sein?
        # Ja! Ein Account kann max 4h am Stück.
        # Also muss der Split so liegen, dass Block A <= 240m und Block B <= 240m (bei 2 Accounts)
        # Wenn wir 3 Accounts haben, ist es flexibler, aber hier simulieren wir max 2 Wechsel.
        
        # Check Limits für 2 Accounts
        len_a = split - req_start
        len_b = min(split + 240, req_end) - split # Wir versuchen nach dem Split max 4h zu holen
        
        if len_a > 240: continue # Erster Block zu lang für einen Account
        
        # Wir suchen Raum A
        r_a = None
        for r in top_candidates:
            inv = get_free_intervals(all_rooms_data[r], req_start, split)
            if any(s == req_start and e == split for s, e in inv):
                r_a = r
                break
        
        if not r_a: continue
        
        # Wir suchen Raum B (ab Split bis so lange wie möglich, max split+240 oder req_end)
        target_end_b = min(split + 240, req_end)
        r_b = None
        for r in top_candidates:
            if r == r_a: continue
            inv = get_free_intervals(all_rooms_data[r], split, target_end_b)
            if any(s == split and e >= target_end_b for s, e in inv):
                r_b = r
                break
        
        if r_a and r_b:
            total_dur = (split - req_start) + (target_end_b - split)
            # Wir wollen maximale Gesamtdauer
            if total_dur > max_continuous:
                max_continuous = total_dur
                best_split = [
                    {"start": m2t(req_start), "end": m2t(split), "room": r_a},
                    {"start": m2t(split), "end": m2t(target_end_b), "room": r_b, "info": "Split"}
                ]
    
    if best_split:
        return best_split
        
    return None

def extract_all_rooms(page):
    print("🔍 Extrahiere ALLE Räume aus dem HTML...")
    # Wir holen ALLES, nicht nur Favoriten
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
    
    # Zusätzlich: Wir müssen wissen, welche Räume es ÜBERHAUPT gibt (auch wenn sie leer sind).
    # Das ist schwieriger via SVG, weil leere Räume keine Rects haben.
    # Workaround: Wir nutzen die PREFERRED_ROOMS + alle, die wir in Bookings finden.
    # Ein Raum, der in der Liste existiert aber keine Rects hat, ist KOMPLETT FREI (Jackpot).
    # Das ist aber riskant zu raten. Wir verlassen uns auf die gefundene Buchungen und die Favoriten.
    # Besser: Wir nehmen an, PREFERRED_ROOMS sind die Basis. Alle anderen gefundenen sind Bonus.
    
    return bookings

def run_scan():
    config = parse_arguments(sys.argv)
    if not config["date"]:
        print("❌ Fehler: Kein Datum angegeben. Nutzung: math_scan_v3.py 12.02.2026 [10:00-18:00] [/x3]")
        return

    print(f"--- 🚀 POWER SCAN V3 ---")
    print(f"Datum: {config['date']}")
    print(f"Zeitfenster: {config['start']} - {config['end']}")
    
    data_dir = resolve_data_dir()
    accs = load_accounts(data_dir / "settings.json")
    
    num_accounts = len(accs)
    if config["accounts_override"]:
        num_accounts = config["accounts_override"]
        print(f"ℹ️ Account-Override aktiv: Rechne mit {num_accounts} Accounts.")
    else:
        print(f"ℹ️ Gefundene Accounts: {num_accounts}")

    session_files = list(data_dir.glob("session_*.json"))
    session_path = session_files[0] if session_files else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(session_path)) if session_path else browser.new_context()
        page = context.new_page()

        try:
            d_parts = config["date"].split(".")
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
                if accs and page.locator("#username").is_visible():
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
                print("ℹ️ Keine Buchungen sichtbar (Oder alles frei).")

            raw_bookings = extract_all_rooms(page)
            
            # Daten strukturieren
            rooms_data = {r: [] for r in PREFERRED_ROOMS} # Start mit Favoriten (auch wenn leer = frei)
            
            # Alle gefundenen Buchungen einsortieren
            for b in raw_bookings:
                if b['room'] not in rooms_data:
                    rooms_data[b['room']] = [] # Neuen Raum entdecken
                
                rooms_data[b['room']].append({
                    'start_m': t2m(b['start']),
                    'end_m': t2m(b['end'])
                })
            
        except Exception as e:
            print(f"❌ Fehler: {e}")
            browser.close()
            return

        browser.close()

        # BERECHNUNG
        req_start = t2m(config["start"])
        req_end = t2m(config["end"])
        
        plan = solve_schedule(rooms_data, num_accounts, req_start, req_end)
        
        if plan:
            print("\n✅ GEFUNDENER OPTIMAL-PLAN:")
            print(json.dumps(plan, indent=2))
        else:
            print("❌ Kein passender Plan machbar.")

if __name__ == "__main__":
    run_scan()
