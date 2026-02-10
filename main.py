import sys
import argparse
import json
import os
from roombooker.storage import StorageManager
from roombooker.intelligence import BookingIntelligence
from roombooker.browser import BrowserEngine, m2t, t2m
from roombooker.calendar_sync import CalendarSync 
from roombooker.jobs import JobManager
from roombooker.config import CREDENTIALS_FILE, BASE_DIR

def run_booking_logic(date_str, start_str, end_str, category, num_accounts, job_id=None):
    store = StorageManager(); brain = BookingIntelligence(store); browser = BrowserEngine(headless=True)
    req_start = t2m(start_str); req_end = t2m(end_str)
    gaps = brain.calculate_gaps(date_str, req_start, req_end)
    if not gaps:
        print(f"[INFO] {date_str}: Alles abgedeckt."); 
        if job_id: JobManager().mark_done(job_id, date_str)
        return
    
    cats = store.get_categories()
    target_rooms = cats.get(category, cats.get("default", {})).get("rooms", [])
    if not target_rooms: print(f"[ERROR] Keine Räume für {category}"); return
    
    print(f"[SCAN] Scanne {len(target_rooms)} Räume...")
    rooms_state = browser.scan_grid(date_str, target_rooms)
    all_accounts = store.get_settings()[:num_accounts] if num_accounts > 0 else store.get_settings()
    
    for g_start, g_end in gaps:
        curr = g_start
        while curr < g_end:
            avail = brain.get_available_accounts(date_str, curr, g_end, all_accounts)
            if not avail: print("[WARN] Keine Accounts!"); break
            best = None
            for r, bookings in rooms_state.items():
                limit = g_end
                for b in sorted(bookings, key=lambda x: x['start']):
                    if b['end'] <= curr: continue
                    if b['start'] < limit: limit = b['start']
                actual_end = min(limit, curr + 240)
                if (actual_end - curr) >= 30:
                    sc = brain.score_room(r, curr, actual_end, date_str)
                    if not best or sc > best['score']: best = {"room": r, "start": curr, "end": actual_end, "score": sc}
            if not best: curr += 30; continue
            
            acc = avail[0]
            print(f">>> BUCHE {best['room']} ({m2t(best['start'])}-{m2t(best['end'])})")
            if browser.perform_booking(date_str, best['room'], best['start'], best['end'], acc):
                brain.record_booking(date_str, best['room'], best['start'], best['end'], acc['email'])
                curr = best['end']; 
                if job_id: JobManager().mark_done(job_id, date_str)
            else: avail.pop(0)

def run_sync():
    cache_file = BASE_DIR / "last_scan.json"
    if cache_file.exists(): os.remove(cache_file)
    print("--- FULL SYNC START ---")
    store = StorageManager(); browser = BrowserEngine(headless=True)
    syncer = CalendarSync(str(CREDENTIALS_FILE))
    all_events = []
    for acc in store.get_settings():
        if not acc.get("active", True): continue
        print(f"[SYNC] Lade Reservationen für {acc['email']}...")
        all_events.extend(browser.get_my_reservations(acc))
    if all_events: syncer.sync_slots(all_events)
    print("--- SYNC DONE ---")

def run_debug_sync():
    print("--- DEBUG SYNC (OFFLINE) ---")
    cache_file = BASE_DIR / "last_scan.json"
    if not cache_file.exists(): print(f"[ERROR] Kein Cache. Bitte erst '4' ausführen."); return
    try:
        with open(cache_file, "r") as f: events = json.load(f)
        print(f"[DEBUG] {len(events)} Events aus Cache.")
        CalendarSync(str(CREDENTIALS_FILE)).sync_slots(events)
    except Exception as e: print(f"[ERROR] {e}")

def start_wizard():
    print("\n--- ROOM BOOKER WIZARD (Fixed) ---")
    print("[1] Einmalige Buchung")
    print("[2] Zukünftige Buchung planen")
    print("[3] Jobs verwalten")
    print("[4] Google Calendar Sync (LIVE)")
    print("[5] Debug Sync (Cache)")
    print("[q] Beenden")
    c = input("Auswahl: ").strip()
    if c == "1":
        d = input("Datum (DD.MM.YYYY): "); s = input("Start: "); e = input("Ende: ")
        run_booking_logic(d, s, e, "default", 4)
    elif c == "2":
        d = input("Datum: "); s = input("Start: "); e = input("Ende: ")
        JobManager().add_job("onetime", target_date=d, time_start=s, time_end=e, category="default")
    elif c == "3":
        for j in JobManager().jobs: print(f"- {j['type']} {j.get('target_date')}")
    elif c == "4": run_sync()
    elif c == "5": run_debug_sync()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-jobs", action="store_true")
    args = parser.parse_args()
    if args.process_jobs:
        jm = JobManager(); due = jm.get_due_jobs()
        for j, d in due: run_booking_logic(d, j['time_start'], j['time_end'], j['category'], 4, job_id=j["id"])
    else:
        try: start_wizard()
        except KeyboardInterrupt: print("\nAbbruch.")
