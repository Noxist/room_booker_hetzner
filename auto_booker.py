import sys
import json
import time
import re
import os
from datetime import datetime
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir

# Default Fallback
KNOWN_ROOMS_ALL = ["A-204", "A-206", "A-231", "A-233", "A-235", "A-237", "A-241", "D-202", "D-204", "D-206", "D-231", "D-233", "D-235", "D-237", "D-239", "D-243"]

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f: return json.load(f)
    return {}

def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0

def perform_login(page, email, password):
    print(f"[LOGIN] {email}...")
    try:
        if "login" not in page.url and "wayf" not in page.url:
            page.goto("https://raumreservation.ub.unibe.ch/event/add")
        if "wayf" in page.url or "login" in page.url:
            page.fill("#username", email)
            page.keyboard.press("Enter")
            time.sleep(1)
            page.fill("#password", password)
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle")
            time.sleep(3)
        return True
    except Exception as e:
        print(f"[ERROR] Login failed: {e}"); return False

def scan_rooms(date_str, allowed_rooms=None):
    d_parts = date_str.split(".")
    iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
    
    # Filter rooms if category provided
    target_rooms = allowed_rooms if allowed_rooms else KNOWN_ROOMS_ALL
    rooms_data = {r: [] for r in target_rooms}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"[SCAN] Loading calendar for {date_str}...")
        try:
            url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(2)
            if "select" in page.url or "Standort" in page.title():
                 page.goto("https://raumreservation.ub.unibe.ch/set/1")
                 page.goto(url, wait_until="domcontentloaded")
                 time.sleep(2)
            try: page.wait_for_selector('rect[data-event-event-value]', timeout=5000)
            except: pass
            
            raw = page.evaluate("""() => Array.from(document.querySelectorAll('rect[data-event-event-value]')).map(el => JSON.parse(el.getAttribute('data-event-event-value')))""")
            count = 0
            for e in raw:
                r = e['roomName']
                if r in rooms_data:
                    rooms_data[r].append({"start_m": t2m(e['start'].split('T')[1][:5]), "end_m": t2m(e['end'].split('T')[1][:5])})
                    count += 1
            print(f"[SCAN] Found {count} bookings in target categories.")
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
        actual_end = min(limit, start + 240)
        duration = actual_end - start
        if duration >= 30: 
            score = duration * weights.get("totalCoveredMin", 0.01)
            # No dynamic favorite bonus here, logic is pre-filtered by category
            candidates.append({"room": room, "start": start, "end": actual_end, "duration": duration, "score": score})
    candidates.sort(key=lambda x: x['score'], reverse=True)
    if not candidates: return []
    best = candidates[0]
    result_chain = [best]
    if accounts > 1 and best['end'] < end:
        remainder = find_best_chain(rooms_data, best['end'], end, accounts - 1, weights)
        if remainder: result_chain.extend(remainder)
    return result_chain

def book_chain(chain, accounts_list, date_str):
    print("\n--- STARTING BOOKING ---")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i, step in enumerate(chain):
            if i >= len(accounts_list):
                print(f"[WARN] Not enough accounts for step {i+1}"); break
            acc = accounts_list[i]
            room = step['room']
            start_t = m2t(step['start'])
            end_t = m2t(step['end'])
            print(f"[BOOK] {start_t}-{end_t} in {room} using {acc.email}...")
            
            context = browser.new_context()
            page = context.new_page()
            try:
                if perform_login(page, acc.email, acc.password):
                    page.goto("https://raumreservation.ub.unibe.ch/event/add")
                    try: page.wait_for_selector("#event_room", timeout=10000)
                    except: print("[ERROR] Dropdown not found"); continue

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
                    
                    if not found:
                        print(f"[ERROR] Room {room} not in list!"); continue
                    
                    time.sleep(1)
                    page.fill("#event_startDate", f"{date_str} {start_t}")
                    page.keyboard.press("Enter")
                    time.sleep(1)
                    dur_min = step['end'] - step['start']
                    page.fill("#event_duration", str(dur_min))
                    page.keyboard.press("Enter")
                    page.fill("#event_title", "Lernen")
                    try: page.check('input[name="event[purpose]"][value="Other"]') 
                    except: pass
                    
                    # SIMULATION
                    # page.click("#event_submit")
                    print(f"[SUCCESS] Booked {room} ({dur_min} min) ✅ (Simulated)")
            except Exception as e:
                print(f"[ERROR] Booking failed: {e}")
            finally: context.close()
        browser.close()

def execute_job(date_str, start_time, end_time, category_key, num_accounts):
    data_dir = resolve_data_dir()
    categories = load_json("categories.json")
    weights = load_json("weights.json") 
    accs = load_accounts(data_dir / "settings.json")
    
    # Resolve category to room list
    cat_data = categories.get(category_key, categories.get("default"))
    target_rooms = cat_data.get("rooms", KNOWN_ROOMS_ALL)
    
    # Resolve accounts
    if isinstance(num_accounts, str) and "max" in num_accounts:
        use_accs = accs
    else:
        try: count = int(num_accounts); use_accs = accs[:count]
        except: use_accs = accs

    print(f"--- EXEC: {date_str} [{category_key.upper()}] ---")
    
    rooms_data = scan_rooms(date_str, target_rooms)
    chain = find_best_chain(rooms_data, t2m(start_time), t2m(end_time), len(use_accs), weights)
    
    if chain:
        print(f"[PLAN] Strategy found ({len(chain)} blocks)")
        book_chain(chain, use_accs, date_arg=date_str)
        return True
    else:
        print("[RESULT] No valid chain found.")
        return False

# Minimal wrapper for direct calls if needed
if __name__ == "__main__":
    if len(sys.argv) > 4:
        # date start end cat accounts
        execute_job(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
