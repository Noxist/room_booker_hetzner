import json
import time
import sys
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from roombooker.storage import load_accounts, resolve_data_dir

DEFAULT_START = "08:00"
DEFAULT_END = "20:00"
MAX_BLOCK_MINUTES = 240

DEFAULT_WEIGHTS = {
    "totalCoveredMin": 0.0141,
    "waitPenalty": -1.453,
    "switchBonus": 1.021,
    "stabilityBonus": 9.352,
    "productiveLossMin": -0.118
}

def t2m(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def m2t(mins):
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

def load_weights(data_dir):
    # VERSUCH 1: Direkt im aktuellen Ordner (wo das Script liegt)
    local_path = Path("weights.json")
    # VERSUCH 2: Im Daten-Ordner
    data_path = data_dir / "weights.json"
    
    weights = DEFAULT_WEIGHTS.copy()
    
    target_path = local_path if local_path.exists() else data_path
    
    if target_path.exists():
        try:
            with open(target_path, "r") as f:
                weights.update(json.load(f))
            print(f"[INFO] Gewichte geladen aus: {target_path}")
        except Exception as e:
            print(f"[WARN] Fehler bei weights.json: {e}")
    else:
        print(f"[INFO] Keine weights.json gefunden (Weder hier noch in {data_dir}). Nutze Standards.")
    return weights

def parse_arguments(args):
    config = {"date": None, "start": DEFAULT_START, "end": DEFAULT_END, "accounts_override": None, "debug": False}
    for arg in args:
        if re.match(r"\d{2}\.\d{2}\.\d{4}", arg): config["date"] = arg
        m_time = re.match(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", arg)
        if m_time: config["start"], config["end"] = m_time.group(1).zfill(5), m_time.group(2).zfill(5)
        m_acc = re.match(r"/x(\d+)", arg)
        if m_acc: config["accounts_override"] = int(m_acc.group(1))
        if arg in ["--debug", "-d"]: config["debug"] = True
    return config

def get_free_duration(bookings, start_time, max_end_time):
    sorted_b = sorted(bookings, key=lambda x: x['start_m'])
    current_limit = max_end_time
    for b in sorted_b:
        if b['end_m'] <= start_time: continue
        if b['start_m'] <= start_time: return start_time 
        if b['start_m'] > start_time:
            current_limit = min(current_limit, b['start_m'])
            break
    return current_limit

def find_best_chain(rooms_data, current_time, target_end, accounts_left, path_history, weights, debug=False, depth=0):
    indent = "  " * depth
    if debug: print(f"{indent}[SEARCH] Suche ab {m2t(current_time)} (Accounts: {accounts_left})")
    if current_time >= target_end: return path_history
    if accounts_left <= 0: return path_history

    candidates = []
    last_room = path_history[-1]['room'] if path_history else None
    
    for room, bookings in rooms_data.items():
        physical_limit = get_free_duration(bookings, current_time, target_end)
        actual_end = min(physical_limit, current_time + MAX_BLOCK_MINUTES)
        duration = actual_end - current_time
        
        if duration >= 15:
            score = duration * weights.get("totalCoveredMin", 0.014)
            details = [f"Dauer:{score:.2f}"]
            if last_room:
                if room == last_room:
                    score += weights.get("stabilityBonus", 9.0)
                    details.append("Stab")
                else:
                    score += weights.get("switchBonus", 1.0)
                    details.append("Wechsel")
            
            candidates.append({"room": room, "start": current_time, "end": actual_end, "duration": duration, "score": score, "details": ",".join(details)})
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    if debug and candidates:
        for c in candidates[:3]: print(f"{indent}   -> {c['room']} ({c['duration']}m) Score:{c['score']:.2f} [{c['details']}]")

    top_candidates = candidates[:6]
    best_full_path = path_history
    best_path_score = -float('inf')
    
    if not top_candidates: return path_history

    for cand in top_candidates:
        new_step = {"start": m2t(cand['start']), "end": m2t(cand['end']), "room": cand['room'], "start_m": cand['start'], "end_m": cand['end']}
        res = find_best_chain(rooms_data, cand['end'], target_end, accounts_left - 1, path_history + [new_step], weights, debug, depth + 1)
        if not res: continue
        
        curr_score = res[-1]['end_m']
        if curr_score > best_path_score:
            best_full_path = res
            best_path_score = curr_score
            
    return best_full_path

def run_scan():
    config = parse_arguments(sys.argv)
    if not config["date"]: return print("[ERROR] Datum fehlt.")
    data_dir = resolve_data_dir()
    weights = load_weights(data_dir)
    print(f"--- CHAIN SCAN V5 (09.02.2026) [DEBUG={config['debug']}] ---")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # TIMEOUT ERHÖHT: 60 Sekunden
        context = browser.new_context()
        context.set_default_timeout(60000) 
        
        page = context.new_page()

        try:
            d_parts = config["date"].split(".")
            target_url = f"https://raumreservation.ub.unibe.ch/event?day={d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
            print(f"[INFO] Lade: {target_url} (Timeout: 60s)")
            
            # Smart Wait
            page.goto(target_url, wait_until="domcontentloaded")
            
            # --- LOGIK: STANDORT AUSWÄHLEN ---
            if "Standort" in page.title() or "select" in page.url:
                print("[INFO] Standort-Auswahl erkannt. Suche Link...")
                
                locs = page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/set/"]'));
                    return links.map(l => ({text: l.innerText.trim(), href: l.getAttribute('href')}));
                }""")
                
                target_loc = None
                for l in locs:
                    if "Unitobler" in l['text'] or "Münstergasse" in l['text']: 
                        target_loc = l
                        break
                if not target_loc and locs: target_loc = locs[0]

                if target_loc:
                    print(f"[INFO] Klicke Standort: {target_loc['text']}")
                    full_href = target_loc['href'] if target_loc['href'].startswith("http") else f"https://raumreservation.ub.unibe.ch{target_loc['href']}"
                    
                    page.goto(full_href, wait_until="domcontentloaded")
                    time.sleep(2)
                    
                    print("[INFO] Kehre zurück zur Kalender-Ansicht...")
                    page.goto(target_url, wait_until="domcontentloaded")
                    # Länger warten, damit Kalender lädt
                    time.sleep(5)
                else:
                    print("[ERROR] Keine Standort-Links gefunden!")
            
            # --- ENDE STANDORT LOGIK ---
            
            try:
                page.wait_for_selector("rect[data-event-event-value]", timeout=15000)
            except:
                print("[WARN] Keine 'rect' Elemente gefunden. Seite evtl. leer oder Login nötig.")

            bookings = page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('rect[data-event-event-value]').forEach(el => {
                    try {
                        const d = JSON.parse(el.getAttribute('data-event-event-value'));
                        if (d.start && d.end && d.roomName) results.push({
                            room: d.roomName, 
                            start: d.start.split('T')[1].substring(0,5), 
                            end: d.end.split('T')[1].substring(0,5)
                        });
                    } catch(e){}
                });
                return results;
            }""")
            
            rooms = {} 
            for b in bookings:
                r = b['room']
                if r not in rooms: rooms[r] = []
                rooms[r].append({'start_m': t2m(b['start']), 'end_m': t2m(b['end'])})
            
            print(f"[INFO] {len(rooms)} Raeume gefunden.")
            
            if len(rooms) > 0:
                chain = find_best_chain(rooms, t2m(config["start"]), t2m(config["end"]), config["accounts_override"] or 1, [], weights, debug=config["debug"])
                if chain:
                    print("\n[RESULT] PLAN:")
                    print(json.dumps([{"start": s["start"], "end": s["end"], "room": s["room"]} for s in chain], indent=2))
                else:
                    print("[RESULT] Keine Kette möglich.")
            else:
                if config["debug"]:
                    print(f"[DEBUG] HTML Preview: {page.content()[:500]}")

        except PlaywrightTimeout:
            print("[ERROR] Timeout! Die Seite hat länger als 60s geladen.")
        except Exception as e:
            print(f"[ERROR] {e}")
        browser.close()

if __name__ == "__main__":
    run_scan()
