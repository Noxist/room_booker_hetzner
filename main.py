import sys
import os
import time
from roombooker.booking_engine import BookingEngine
from roombooker.storage import StorageManager
from roombooker.calendar_sync import CalendarSync
from roombooker.jobs import JobManager
from roombooker.config import BASE_DIR, GOOGLE_CREDS

STATUS_FILE = BASE_DIR / "web_status.txt"

def set_web_status(msg, state="info"):
    try:
        with open(STATUS_FILE, "w") as f: f.write(f"{state}|{msg}")
    except: pass

def run_sync():
    set_web_status("Synchronisiere Kalender...", "info")
    print("[SYNC] Starte manuellen Sync...")
    try:
        # Nutzung der stabilen CalendarSync Klasse
        sync = CalendarSync(service_account_file=str(GOOGLE_CREDS))
        sync.sync_all()
        print("[SYNC] Fertig.")
        set_web_status("Kalender synchronisiert ✅", "success")
    except Exception as e:
        print(f"[SYNC] Fehler: {e}")
        set_web_status(f"Sync Fehler: {e}", "error")

def run_booking_logic(date_str, start_time, end_time, category_key, num_accounts, job_id=None):
    set_web_status(f"Starte Job für {date_str}...", "info")
    
    store = StorageManager()
    engine = BookingEngine(BASE_DIR)
    
    cats = store.get_categories()
    # Fallback für Category
    cat_data = cats.get(category_key, cats.get("default", {}))
    target_rooms = cat_data.get("rooms", ["A-204"])
    
    print(f"\n[JOB] {date_str} {start_time}-{end_time} | R: {len(target_rooms)} | Acc: {num_accounts}")
    
    try:
        # Hier nutzen wir die intelligente Chaining-Funktion der Engine
        success = engine.book_chain(date_str, start_time, end_time, target_rooms)
        
        if success:
            msg = "Buchung erfolgreich abgeschlossen! ✅"
            print(f"[JOB] {msg}")
            set_web_status(msg, "success")
            if job_id: JobManager().mark_done(job_id, date_str)
            
            # Auto-Sync nach Erfolg
            try: run_sync()
            except: pass
        else:
            msg = "Konnte nicht alle Slots füllen (Voll/Fehler). ⚠️"
            print(f"[JOB] {msg}")
            set_web_status(msg, "warning")
            
    except Exception as e:
        print(f"[JOB CRASH] {e}")
        set_web_status(f"Crash: {e}", "error")

if __name__ == "__main__":
    pass
