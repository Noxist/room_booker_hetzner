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
        with open(STATUS_FILE, "w") as f: f.write(f"{state}|{msg}")
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
    
    print(f"\n[JOB] {date_str} {start_time}-{end_time} | Ziel-Räume: {target_rooms}")
    
    try:
        # Check for existing bookings and detect conflicts
        from roombooker.utils import parse_time_to_minutes
        start_min = parse_time_to_minutes(start_time)
        end_min = parse_time_to_minutes(end_time)
        
        history = sm.get_history()
        date_bookings = history.get(date_str, [])
        
        # Find conflicts
        conflicting = []
        for booking in date_bookings:
            b_start = booking.get('start', 0)
            b_end = booking.get('end', 0)
            # Check overlap
            if not (end_min <= b_start or start_min >= b_end):
                conflicting.append(booking)
        
        if conflicting:
            msg = f"⚠️ {len(conflicting)} Buchung(en) überschneiden sich bereits"
            print(f"[WARNING] {msg}")
            set_web_status(msg, "warning")
        
        # Robuste Buchungskette starten
        success = engine.book_chain(date_str, start_time, end_time, target_rooms)
        
        if success:
            # Get the actual booked room and account info from recent history
            updated_history = sm.get_history()
            new_bookings = updated_history.get(date_str, [])
            
            # Find the booking we just made
            recent_booking = None
            for booking in new_bookings:
                if booking.get('start') == start_min and booking.get('end') == end_min:
                    recent_booking = booking
                    break
            
            if recent_booking:
                room = recent_booking.get('room', '?')
                account = recent_booking.get('account', '?')
                msg = f"✅ Raum {room} gebucht mit {account}!"
            else:
                msg = "Buchung erfolgreich! ✅"
            
            print(f"[JOB] {msg}")
            set_web_status(msg, "success")
            
            # Job erledigen
            if job_id: 
                JobManager().mark_done(job_id, date_str)
        else:
            msg = "❌ Kein Raum/Account verfügbar"
            set_web_status(msg, "error")
            
    except Exception as e:
        print(f"[CRASH] {e}")
        import traceback
        traceback.print_exc()
        set_web_status(f"❌ Fehler: {e}", "error")

if __name__ == "__main__":
    pass
