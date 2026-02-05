import json
import time
import sys
import re
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir

# --- KONFIGURATION ---
PREFERRED_ROOMS = ["D-204", "A-204", "A-241", "D-239", "D-231", "A-231", "D-202", "D-235"]
DEFAULT_START = "08:00"
DEFAULT_END = "20:00"
MAX_BLOCK_MINUTES = 240  # Ein Account kann max 4h am Stück buchen

def t2m(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def m2t(mins):
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

def parse_arguments(args):
    config = {
        "date": None,
        "start": DEFAULT_START,
        "end": DEFAULT_END,
        "accounts_override": None
    }
    for arg in args:
        if re.match(r"\d{2}\.\d{2}\.\d{4}", arg):
            config["date"] = arg
        match_time = re.match(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", arg)
        if match_time:
            config["start"] = match_time.group(1).zfill(5)
            config["end"] = match_time.group(2).zfill(5)
        match_acc = re.match(r"/x(\d+)", arg)
        if match_acc:
            config["accounts_override"] = int(match_acc.group(1))
    return config

def get_free_duration(bookings, start_time, max_end_time):
    """
    Gibt zurück, bis zu welcher Minute der Raum ab start_time frei ist.
    Maximal bis max_end_time.
    """
    sorted_b = sorted(bookings, key=lambda x: x['start_m'])
    current_limit = max_end_time
    
    for b in sorted_b:
        if b['end_m'] <= start_time: continue
        if b['start_m'] <= start_time:
            return start_time # Sofort blockiert
        if b['start_m'] > start_time:
            current_limit = min(current_limit, b['start_m'])
            break
            
    return current_limit

def find_best_chain(rooms_data, current_time, target_end, accounts_left, path_history):
    """
    Rekursiver Pfadfinder. Versucht von current_time bis target_end zu kommen.
    """
    if current_time >= target_end:
        return path_history
    
    if accounts_left <= 0:
        return path_history

    candidates = []
    all_rooms = list(rooms_data.keys())
    
    for room in all_rooms:
        bookings = rooms_data.get(room, [])
        physical_limit = get_free_duration(bookings, current_time, target_end)
        account_limit = current_time + MAX_BLOCK_MINUTES
        actual_end = min(physical_limit, account_limit)
        duration = actual_end - current_time
        
        if duration >= 15: # Mindestens 15 min Slots
            score = duration
            if room in PREFERRED_ROOMS:
                score += 30 
            
            candidates.append({
                "room": room,
                "start": current_time,
                "end": actual_end,
                "duration": duration,
                "score": score
            })
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    top_candidates = candidates[:8] # Etwas breiter suchen
    
    best_full_path = path_history
    
    for cand in top_candidates:
        new_step = {
            "start": m2t(cand['start']),
            "end": m2t(cand['end']),
            "room": cand['room'],
            "start_m": cand['start'],
            "end_m": cand['end']
        }
        
        result_path = find_best_chain(
            rooms_data, 
            cand['end'], 
            target_end, 
            accounts_left - 1, 
            path_history + [new_step]
        )
        
        if not result_path: continue
        
        final_end = result_path[-1]['end_m']
        current_max_end = best_full_path[-1]['end_m'] if best_full_path else 0
        
        if final_end > current_max_end:
            best_full_path = result_path
        elif final_end == current_max_end:
            # Bei gleicher Reichweite: Weniger Schritte (=weniger Wechsel) ist besser
            if len(result_path) < len(best_full_path):
                best_full_path = result_path
            # Bei gleicher Länge und Schritten: Mehr Zeit in Favoriten? (egal hier)
    
    return best_full_path

def extract_all_rooms(page):
    print("🔍 Extrahiere ALLE Räume aus dem HTML...")
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

def run_scan():
    config = parse_arguments(sys.argv)
    if not config["date"]:
        print("❌ Fehler: Kein Datum. Bsp: python3 math_scan_v4.py 12.02.2026 /x5")
        return

    print(f"--- 🔗 CHAIN SCAN V4 ({config['date']}) ---")
    data_dir = resolve_data_dir()
    accs = load_accounts(data_dir / "settings.json")
    
    num_accounts = config["accounts_override"] if config["accounts_override"] else len(accs)
    print(f"ℹ️ Accounts: {num_accounts} | Ziel: {config['start']} - {config['end']}")

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
            
            print(f"Lade Daten von: {target_url}")
            page.goto(target_url)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            if "/select" in page.url:
                page.goto("https://raumreservation.ub.unibe.ch/set/1")
                time.sleep(1)
                page.goto(target_url)
                time.sleep(2)

            if "login" in page.url or "wayf" in page.url:
                if accs and page.locator("#username").is_visible():
                    print("⚠️ Logge ein...")
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
                print("ℹ️ Keine Buchungen gefunden (Alles frei?).")

            raw_bookings = extract_all_rooms(page)
            
            # Daten aufbereiten
            rooms_data = {r: [] for r in PREFERRED_ROOMS} 
            for b in raw_bookings:
                r = b['room']
                if r not in rooms_data: rooms_data[r] = []
                rooms_data[r].append({'start_m': t2m(b['start']), 'end_m': t2m(b['end'])})
            
        except Exception as e:
            print(f"❌ Fehler: {e}")
            browser.close()
            return
        browser.close()

    print("🧮 Berechne beste Kette...")
    req_start = t2m(config["start"])
    req_end = t2m(config["end"])
    
    chain = find_best_chain(rooms_data, req_start, req_end, num_accounts, [])
    
    if chain:
        clean_chain = []
        for step in chain:
            clean_chain.append({
                "start": step["start"],
                "end": step["end"],
                "room": step["room"]
            })
        
        print("\n✅ OPTIMALER KETTEN-PLAN:")
        print(json.dumps(clean_chain, indent=2))
        
        total_min = chain[-1]['end_m'] - chain[0]['start_m']
        print(f"\n📊 Abdeckung: {total_min/60:.1f} Stunden ({len(chain)} Buchungen)")
        if chain[-1]['end_m'] < req_end:
            print(f"⚠️ Ziel 20:00 verfehlt. Ende um {chain[-1]['end']}.")
    else:
        print("❌ Keine machbare Kette gefunden.")

if __name__ == "__main__":
    run_scan()
