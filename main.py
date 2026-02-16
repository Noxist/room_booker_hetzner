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
        ts = int(time.time())
        with open(STATUS_FILE, "w") as f:
            f.write(f"{state}|{msg}|{ts}")
    except Exception:
        pass


def run_sync():
    set_web_status("Starte echten Kalender-Scan...", "info")
    print("\n[SYNC] >>> STARTE ECHTZEIT-SCAN ALLER ACCOUNTS <<<")

    sm = StorageManager()
    accounts = sm.get_settings()

    browser = BrowserEngine(headless=True)
    all_real_bookings = []

    for acc in accounts:
        if not acc.get('active', True):
            continue
        print(f"--- Scanne Account: {acc['email']} ---")
        try:
            bookings = browser.get_my_reservations(acc)
            all_real_bookings.extend(bookings)
        except Exception as e:
            print(f"[ERROR] Scan fehlgeschlagen fuer {acc['email']}: {e}")

    print(f"\n[SYNC] Gefundene Reservationen total: {len(all_real_bookings)}")

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
    set_web_status(f"Starte Job fuer {date_str} {start_time}-{end_time}...", "info")

    engine = BookingEngine(BASE_DIR)
    sm = StorageManager()

    # Load target rooms from category
    cats = sm.get_categories()
    if category_key not in cats:
        category_key = "default"
    target_rooms = cats.get(category_key, {}).get("rooms", [])
    if not target_rooms:
        # Fallback: use all rooms from default category
        target_rooms = cats.get("default", {}).get("rooms", [])

    print(f"\n[JOB] {date_str} {start_time}-{end_time} | Kategorie: {category_key} | Raeume: {target_rooms}")

    try:
        from roombooker.utils import parse_time_to_minutes
        start_min = parse_time_to_minutes(start_time)
        end_min = parse_time_to_minutes(end_time)

        # Book
        success = engine.book_chain(
            date_str, start_time, end_time, target_rooms,
            category_key, job_id
        )

        if success:
            updated_history = sm.get_history()
            new_bookings = updated_history.get(date_str, [])

            # Find the most recent booking for this job
            recent_booking = None
            for booking in reversed(new_bookings):
                if booking.get('job_id') == job_id:
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
