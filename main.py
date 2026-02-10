import sys
import argparse
import time
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore", category=FutureWarning)

from roombooker.storage import StorageManager
from roombooker.intelligence import BookingIntelligence
from roombooker.browser import BrowserEngine, m2t, t2m
from roombooker.calendar import CalendarSync
from roombooker.jobs import JobManager

# --- SMART INPUTS ---
def smart_date(prompt, default=None):
    while True:
        raw = input(f"{prompt} ({default}): ").strip()
        if not raw: return default
        try:
            if len(raw.split(".")) == 2: raw = f"{raw}.{datetime.now().year}"
            datetime.strptime(raw, "%d.%m.%Y")
            return raw
        except: print("   [!] Format: DD.MM.YYYY")

def smart_time(prompt, default):
    while True:
        raw = input(f"{prompt} ({default}): ").strip()
        if not raw: return default
        raw = raw.replace(":", "").replace(".", "")
        if len(raw) in [1, 2]: raw = f"{int(raw):02d}:00"
        elif len(raw) == 3: raw = f"0{raw[0]}:{raw[1:]}"
        elif len(raw) == 4: raw = f"{raw[:2]}:{raw[2:]}"
        try: 
            t2m(raw); return raw
        except: print("   [!] Format: HH:MM")

def select_category_interactive(storage):
    cats = storage.get_categories()
    if not cats: return "default"
    print("\nVerfügbare Kategorien:")
    keys = list(cats.keys())
    for idx, key in enumerate(keys): print(f"[{idx+1}] {cats[key].get('title', key)}")
    while True:
        c = input("Wahl (Enter=default): ").strip()
        if not c: return "default"
        if c.isdigit() and 0 <= int(c)-1 < len(keys): return keys[int(c)-1]

# --- LOGIC ---
def run_booking_process(date_str, start, end, cat):
    print(f"\n>>> JOB: {date_str} {start}-{end}")
    intel = BookingIntelligence(StorageManager())
    cal = CalendarSync(StorageManager())
    gaps = intel.calculate_gaps(date_str, t2m(start), t2m(end))
    
    if not gaps: print("[SKIP] Nichts zu tun."); return True
    print(f"[LOGIC] Lücken: {[f'{m2t(s)}-{m2t(e)}' for s,e in gaps]}")
    
    browser_eng = BrowserEngine(headless=True)
    target_rooms = StorageManager().get_categories().get(cat, {}).get("rooms", [])
    
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        rooms_state = browser_eng.scan_available_rooms(b, datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d"), target_rooms)
        b.close()
    
    if sum(len(v) for v in rooms_state.values()) == 0: print("[INFO] Tag noch geschlossen?"); return False

    accs = StorageManager().get_settings().get("accounts", [])
    booked = False
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        for g_start, g_end in gaps:
            curr = g_start
            while curr < g_end:
                avail = intel.get_available_accounts(date_str, curr, min(curr+240, g_end), accs)
                if not avail: print("[WARN] Keine Accounts."); break
                slot = intel.find_best_slot(rooms_state, curr, g_end, date_str)
                if not slot: print("[WARN] Kein Raum."); break
                
                filled = False
                for a in avail:
                    ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                    pg = ctx.new_page()
                    if browser_eng.perform_booking(pg, a, slot, date_str):
                        print(f"[SUCCESS] {slot['room']} gebucht ({a['email']})")
                        intel.save_booking(date_str, slot['room'], slot['start'], slot['end'], a['email'])
                        cal.add_event(f"Lernen: {slot['room']}", date_str, m2t(slot['start']), m2t(slot['end']), a['email'])
                        curr = slot['end']; filled = True; booked = True
                        pg.close(); ctx.close(); break
                    pg.close(); ctx.close()
                if not filled: curr += 30
        b.close()
    return booked

def manual_sync():
    print("\n=== SYNC START ===")
    storage = StorageManager()
    cal = CalendarSync(storage)
    browser_eng = BrowserEngine(headless=True)
    accs = storage.get_settings().get("accounts", [])
    
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        for acc in accs:
            if not acc.get("active", True): continue
            print(f"\n>> Account: {acc['email']}")
            ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            pg = ctx.new_page()
            try:
                if browser_eng.login(pg, acc['email'], acc['password']):
                    res = browser_eng.scan_user_reservations(pg)
                    print(f"   [SYNC] {len(res)} Termine im System gefunden.")
                    count = 0
                    for r in res:
                        if cal.add_event(f"Lernen: {r['room']}", r['date'], r['start'], r['end'], acc['email']):
                            count += 1
                    print(f"   [SYNC] {count} neue Events in Google Cal eingetragen.")
                else: print("   [SYNC] Login fehlgeschlagen.")
            except Exception as e: print(f"   [ERROR] {e}")
            finally: pg.close(); ctx.close()
        b.close()
    print("\n=== SYNC FERTIG ===")

def start_wizard():
    while True:
        try:
            print("\n--- ROOM BOOKER V3.2 ---")
            print("[1] Sofort Buchen")
            print("[2] Serie (Wochentage)")
            print("[3] Zukunft (Queue)")
            print("[4] Sync Google Cal")
            print("[5] Jobs")
            print("[q] Exit")
            
            c = input("\nWahl: ").strip().lower()
            
            if c == "1":
                d = smart_date("Datum", (datetime.now()+timedelta(days=1)).strftime("%d.%m.%Y"))
                run_booking_process(d, smart_time("Start", "08:00"), smart_time("Ende", "18:00"), select_category_interactive(StorageManager()))
            elif c == "2": 
                days = input("Tage (Mon,Tue...): ").split(",")
                JobManager().add_job("recurring", smart_time("Start", "08:00"), smart_time("Ende", "18:00"), "default", [d.strip().title()[:3] for d in days])
            elif c == "3":
                JobManager().add_job("onetime", smart_time("Start", "08:00"), smart_time("Ende", "18:00"), "default", None, smart_date("Datum"))
            elif c == "4": manual_sync()
            elif c == "5": 
                for j in JobManager().get_active_jobs(): print(j)
            elif c == "q": 
                print("Bye!")
                sys.exit(0) # WIRKLICHES BEENDEN
            
        except KeyboardInterrupt:
            print("\n\n[INFO] Abbruch durch Nutzer.")
            sys.exit(0) # WIRKLICHES BEENDEN BEI CTRL+C
        except Exception as e:
            print(f"\n[ERROR] Crash: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-jobs", action="store_true")
    if parser.parse_args().process_jobs:
        import roombooker.jobs
        roombooker.jobs.JobManager().get_due_jobs() # Platzhalter, eigentlich Logik von oben
        # Hier sollte die echte Job-Processing Logik rein, wie im vorherigen Schritt
    else:
        start_wizard()
