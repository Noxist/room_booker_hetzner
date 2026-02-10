import sys
import argparse
from datetime import datetime
from roombooker.storage import StorageManager
from roombooker.intelligence import BookingIntelligence
from roombooker.browser import BrowserEngine, m2t, t2m
from roombooker.calendar_sync import CalendarSync 
from roombooker.jobs import JobManager
from roombooker.config import CREDENTIALS_FILE

# Fallback URL Definition
URL_BASE = "https://raumreservation.ub.unibe.ch"

def run_booking_logic(date_str, start_str, end_str, category, num_accounts, job_id=None):
    store = StorageManager()
    brain = BookingIntelligence(store)
    browser = BrowserEngine(headless=True)
    
    req_start = t2m(start_str)
    req_end = t2m(end_str)
    
    # 1. Gaps
    gaps = brain.calculate_gaps(date_str, req_start, req_end)
    if not gaps:
        print(f"[INFO] {date_str}: Alles bereits abgedeckt.")
        if job_id: JobManager().mark_done(job_id, date_str)
        return

    # 2. Scan
    cats = store.get_categories()
    target_rooms = cats.get(category, cats.get("default", {})).get("rooms", [])
    rooms_state = browser.scan_grid(date_str, target_rooms)
    
    # 3. Buchen
    all_accounts = store.get_settings()
    if num_accounts > 0: all_accounts = all_accounts[:num_accounts]
        
    for g_start, g_end in gaps:
        curr = g_start
        while curr < g_end:
            avail_accs = brain.get_available_accounts(date_str, curr, g_end, all_accounts)
            if not avail_accs: break
                
            best = None
            for room, bookings in rooms_state.items():
                limit = g_end
                sorted_b = sorted(bookings, key=lambda x: x['start'])
                for b in sorted_b:
                    if b['end'] <= curr: continue
                    if b['start'] < limit: limit = b['start']
                actual_end = min(limit, curr + 240)
                if (actual_end - curr) >= 30:
                    score = brain.score_room(room, curr, actual_end, date_str)
                    if not best or score > best['score']:
                        best = {"room": room, "start": curr, "end": actual_end, "score": score}
            
            if not best:
                curr += 30; continue
                
            acc = avail_accs[0]
            print(f">>> BUCHE {best['room']} ({m2t(best['start'])}-{m2t(best['end'])})")
            if browser.perform_booking(date_str, best['room'], best['start'], best['end'], acc):
                brain.record_booking(date_str, best['room'], best['start'], best['end'], acc['email'])
                curr = best['end']
                if job_id: JobManager().mark_done(job_id, date_str)
            else:
                avail_accs.pop(0)

def start_wizard():
    print("\n--- ROOM BOOKER WIZARD (V3 Smart) ---")
    print("[1] Einmalige Buchung (Sofort)")
    print("[2] Zukünftige Buchung planen (Smart Wait)")
    print("[3] Jobs verwalten")
    print("[q] Beenden")
    
    c = input("Auswahl: ").strip()
    if c == "1":
        d = input("Datum (DD.MM.YYYY): ")
        s = input("Start (HH:MM): ")
        e = input("Ende (HH:MM): ")
        run_booking_logic(d, s, e, "default", 4)
    elif c == "2":
        d = input("Zieldatum (DD.MM.YYYY): ")
        s = input("Start (HH:MM): ")
        e = input("Ende (HH:MM): ")
        JobManager().add_job("onetime", target_date=d, time_start=s, time_end=e, category="default")
        print("[SUCCESS] Job gespeichert. Der Runner wird ihn ausführen, sobald das Zeitfenster offen ist.")
    elif c == "3":
        print("Jobs:")
        jm = JobManager()
        for j in jm.jobs:
            print(f" - {j['type']} {j.get('target_date')} Active: {j['active']}")

def process_jobs():
    print("[RUNNER] Prüfe anstehende Jobs...")
    jm = JobManager()
    due = jm.get_due_jobs()
    if not due:
        print("[RUNNER] Nichts zu tun (Alles >14 Tage oder erledigt).")
        return

    for job, date_str in due:
        print(f"[RUNNER] Führe Job aus: {date_str} {job['time_start']}-{job['time_end']}")
        run_booking_logic(date_str, job['time_start'], job['time_end'], job['category'], 4, job_id=job["id"])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-jobs", action="store_true", help="Run scheduled jobs")
    args = parser.parse_args()
    
    if args.process_jobs:
        process_jobs()
    else:
        start_wizard()
