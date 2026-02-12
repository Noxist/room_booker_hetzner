import sys
import os
from roombooker.booking_engine import BookingEngine
from roombooker.storage import StorageManager
from roombooker.calendar_sync import CalendarSync
from roombooker.jobs import JobManager
from roombooker.browser import BrowserEngine
from roombooker.config import BASE_DIR, GOOGLE_CREDS

STATUS_FILE = BASE_DIR / "web_status.txt"

def set_web_status(msg, state="info"):
    try:
        with open(STATUS_FILE, "w") as f: f.write(f"{state}|{msg}")
    except: pass

def run_sync():
    set_web_status("Starte echten Kalender-Scan...", "info")
    print("\n[SYNC] >>> STARTE ECHTZEIT-SCAN ALLER ACCOUNTS <<<")
    
    sm = StorageManager()
    accounts = sm.get_settings()
    browser = BrowserEngine(headless=True)
    all_real_bookings = []

    # 1. Alle Accounts scannen
    for acc in accounts:
        if not acc.get('active', True): continue
        print(f"--- Scanne Account: {acc['email']} ---")
        try:
            bookings = browser.scan_reservations(acc)
            all_real_bookings.extend(bookings)
        except Exception as e:
            print(f"[ERROR] Scan fehlgeschlagen für {acc['email']}: {e}")

    # 2. Sync mit Google
    print(f"\n[SYNC] Gefundene Reservationen total: {len(all_real_bookings)}")
    if all_real_bookings:
        try:
            sync_tool = CalendarSync(service_account_file=str(GOOGLE_CREDS))
            sync_tool.sync_scanned_bookings(all_real_bookings)
            set_web_status("Kalender erfolgreich synchronisiert ✅", "success")
        except Exception as e:
            print(f"[SYNC ERROR] {e}")
            set_web_status(f"Sync Fehler: {e}", "error")
    else:
        print("[SYNC] Keine Reservationen gefunden.")
        set_web_status("Keine aktiven Reservationen gefunden.", "success")

def run_booking_logic(date_str, start_time, end_time, category_key, num_accounts, job_id=None):
    set_web_status(f"Starte Job für {date_str}...", "info")
    engine = BookingEngine(BASE_DIR)
    sm = StorageManager()
    cats = sm.get_categories()
    cat_data = cats.get(category_key, cats.get("default", {}))
    target_rooms = cat_data.get("rooms", ["A-204"])
    
    print(f"\n[JOB] {date_str} {start_time}-{end_time} | R: {len(target_rooms)}")
    
    try:
        success = engine.book_chain(date_str, start_time, end_time, target_rooms)
        if success:
            msg = "Buchung erfolgreich! ✅"
            print(f"[JOB] {msg}")
            set_web_status(msg, "success")
            if job_id: JobManager().mark_done(job_id, date_str)
            # Nach Buchung direkt syncen
            run_sync()
        else:
            set_web_status("Konnte nicht vollständig buchen. ⚠️", "warning")
    except Exception as e:
        print(f"[CRASH] {e}")
        set_web_status(f"Fehler: {e}", "error")

if __name__ == "__main__":
    pass
