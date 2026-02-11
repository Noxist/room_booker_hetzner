import sys, time, argparse, random, json, os
from roombooker.booking_engine import BookingEngine
from roombooker.storage import StorageManager
from roombooker.calendar_sync import CalendarSync
from roombooker.jobs import JobManager

STATUS_FILE = "/root/auto_reserve_data/web_status.txt"

def log(msg):
    sys.stderr.write(f"[LOG] {msg}\n")
    sys.stderr.flush()

def set_web_status(msg, state="info"):
    try:
        with open(STATUS_FILE, "w") as f:
            f.write(f"{state}|{msg}")
    except: pass
    log(f"STATUS: {msg}")

def run_sync():
    log("Starte Sync...")
    try:
        CalendarSync().sync_all()
        set_web_status("Kalender synchronisiert ✅", "success")
    except Exception as e: 
        set_web_status(f"Sync Fehler: {e}", "error")

def check_overlap(s1, e1, s2, e2):
    return max(s1, s2) < min(e1, e2)

def run_booking_logic(date_str, start_time, end_time, category_key, num_accounts, job_id=None):
    log(f">>> JOB START: {date_str} {start_time}-{end_time} <<<")
    set_web_status(f"Analysiere {date_str}...", "info")
    
    try:
        sm = StorageManager()
        settings = sm.get_settings()
        last_scan = sm.load_last_scan()
        
        # --- FIX: Daten bereinigen ---
        # Entfernt Einträge aus last_scan, die keine Dictionaries sind (z.B. Strings)
        clean_scan = [e for e in last_scan if isinstance(e, dict)]
        if len(clean_scan) < len(last_scan):
            log(f"WARNUNG: {len(last_scan) - len(clean_scan)} fehlerhafte Einträge ignoriert.")
        last_scan = clean_scan
        # -----------------------------
        
        available = []
        for acc in settings:
            # FIX: Sicherstellen, dass Account ein Dict ist
            if not isinstance(acc, dict): continue
            
            email = acc.get('email')
            if not email: continue

            blocked = False
            for e in last_scan:
                if e.get('account') == email and e.get('date') == date_str:
                    if check_overlap(start_time, end_time, e.get('start', ''), e.get('end', '')):
                        log(f"[BLOCK] {email} ist belegt.")
                        blocked = True; break
            if not blocked: available.append(acc)
        
        log(f"Verfügbare Accounts: {len(available)}")
                
        if not available:
            set_web_status("Alle Accounts belegt! ❌", "error"); return

        engine = BookingEngine(sm.base_dir)
        engine.settings = available
        t_rooms = sm.get_rooms_by_category(category_key)
        
        rooms_state = engine.browser.scan_grid(date_str, t_rooms)
        needed = engine.intelligence.calculate_needed_slots(start_time, end_time, rooms_state, last_scan)
        
        if not needed:
            set_web_status("Alles abgedeckt! ✅", "success")
            if job_id: JobManager().mark_done(job_id, date_str)
            return

        set_web_status(f"Buche {len(needed)} Slot(s)...", "info")
        count = 0
        for slot in needed:
            if engine.book_slot(slot, date_str): count += 1
        
        if count > 0:
            if job_id: JobManager().mark_done(job_id, date_str)
            try: CalendarSync().sync_all()
            except: pass
            set_web_status(f"Fertig! ✅", "success")
        else: set_web_status("Fehler/Voll ❌", "error")
        
    except Exception as e:
        log(f"CRASH: {e}")
        import traceback
        traceback.print_exc()
        set_web_status(f"Fehler: {e}", "error")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-jobs", action="store_true")
    args = parser.parse_args()
    
    if args.process_jobs:
        # Manueller CLI Modus (für Tests)
        jm = JobManager()
        for job, t_date in jm.get_due_jobs():
            run_booking_logic(t_date, job['time_start'], job['time_end'], job.get('category','default'), 4, job['id'])
