import sys
import os
import time
from roombooker.booking_engine import BookingEngine
from roombooker.storage import StorageManager
from roombooker.calendar_sync import CalendarSync
from roombooker.jobs import JobManager
from roombooker.browser import BrowserEngine
from roombooker.config import BASE_DIR, STATUS_FILE, CREDENTIALS_FILE

def set_web_status(msg, state="info"):
    try:
        import time
        ts = int(time.time())
        with open(STATUS_FILE, "w") as f: f.write(f"{state}|{msg}|{ts}")
    except: pass

def run_sync():
    set_web_status("Starte echten Kalender-Scan...", "info")
    print("\n[SYNC] >>> STARTE ECHTZEIT-SCAN ALLER ACCOUNTS <<<")
    
    sm = StorageManager()
    accounts = sm.get_settings()
    
    # Nutzt deinen perfekten Browser Code
    browser = BrowserEngine(headless=True)
    all_real_bookings = []

    for acc in accounts:
        if not acc.get('active', True): continue
        print(f"--- Scanne Account: {acc['email']} ---")
        try:
            # Hier nutzen wir get_my_reservations
            bookings = browser.get_my_reservations(acc)
            all_real_bookings.extend(bookings)
        except Exception as e:
            print(f"[ERROR] Scan fehlgeschlagen für {acc['email']}: {e}")

    print(f"\n[SYNC] Gefundene Reservationen total: {len(all_real_bookings)}")
    
    # Google Sync nur wenn Credentials da sind
    if CREDENTIALS_FILE.exists() and all_real_bookings:
        try:
            sync_tool = CalendarSync(service_account_file=str(CREDENTIALS_FILE))
            sync_tool.sync_scanned_bookings(all_real_bookings)
            set_web_status(f"Sync erfolgreich: {len(all_real_bookings)} Termine", "success")
        except Exception as e:
            print(f"[SYNC ERROR] {e}")
            set_web_status(f"Sync Fehler: {e}", "error")
    else:
        set_web_status(f"Scan fertig. {len(all_real_bookings)} gefunden.", "success")


def run_booking_logic(date_str, start_time, end_time, category_key, num_accounts, job_id=None):
    set_web_status(f"Starte Job für {date_str} {start_time}-{end_time}...", "info")
    
    engine = BookingEngine(BASE_DIR)
    sm = StorageManager()
    
    # Kategorien laden
    cats = sm.get_categories()
    if category_key not in cats: category_key = "default"
    target_rooms = cats.get(category_key, {}).get("rooms", ["A-204", "A-206"])
    
    print(f"\n[JOB] {date_str} {start_time}-{end_time} | Kategorie: {category_key} | Räume: {target_rooms}")
    
    try:
        from roombooker.utils import parse_time_to_minutes
        start_min = parse_time_to_minutes(start_time)
        end_min = parse_time_to_minutes(end_time)
        
        # ── Check for overlapping UNBOOKED jobs and merge them ──
        from roombooker.jobs import JobManager
        jm = JobManager()
        merged = False
        for existing_job in jm.jobs:
            if not existing_job.get('active', True):
                continue
            ej_date = existing_job.get('target_date') or existing_job.get('date_str', '')
            if ej_date != date_str:
                continue
            if job_id and existing_job.get('id') == job_id:
                continue  # skip self
            
            ej_start = parse_time_to_minutes(existing_job.get('start') or existing_job.get('time_start', '08:00'))
            ej_end = parse_time_to_minutes(existing_job.get('end') or existing_job.get('time_end', '12:00'))
            
            # Check overlap
            if not (end_min <= ej_start or start_min >= ej_end):
                # Overlapping unbooked job → merge
                new_start = min(start_min, ej_start)
                new_end = max(end_min, ej_end)
                new_start_str = f"{new_start//60:02d}:{new_start%60:02d}"
                new_end_str = f"{new_end//60:02d}:{new_end%60:02d}"
                
                existing_job['start'] = new_start_str
                existing_job['time_start'] = new_start_str
                existing_job['end'] = new_end_str
                existing_job['time_end'] = new_end_str
                jm.save_jobs()
                
                print(f"[JOB] Merge: Job {existing_job['id']} erweitert auf {new_start_str}-{new_end_str}")
                
                start_time = new_start_str
                end_time = new_end_str
                start_min = new_start
                end_min = new_end
                if not job_id:
                    job_id = existing_job['id']
                merged = True
                break
        
        # ── Book ──
        success = engine.book_chain(date_str, start_time, end_time, target_rooms,
                                    category_key, job_id)
        
        if success:
            updated_history = sm.get_history()
            new_bookings = updated_history.get(date_str, [])
            
            recent_booking = None
            for booking in new_bookings:
                if booking.get('start') == start_min and booking.get('end') == end_min:
                    recent_booking = booking
                    break
            
            if recent_booking:
                room = recent_booking.get('room', '?')
                account = recent_booking.get('account', '?')
                msg = f"Raum {room} gebucht mit {account}"
            else:
                msg = "Buchung erfolgreich"
            
            print(f"[JOB] {msg}")
            set_web_status(msg, "success")
            
            if job_id: 
                JobManager().mark_done(job_id, date_str)
        else:
            msg = "Kein Raum/Account verfuegbar"
            set_web_status(msg, "error")
            
    except Exception as e:
        print(f"[CRASH] {e}")
        import traceback
        traceback.print_exc()
        set_web_status(f"Fehler: {e}", "error")

if __name__ == "__main__":
    pass
