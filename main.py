import sys, os
from roombooker.storage import StorageManager
from roombooker.booking_engine import BookingEngine
from roombooker.config import BASE_DIR, GOOGLE_CREDS

def run_booking_logic(date_str, start_t, end_t, cat_key, num_accounts=4):
    store = StorageManager()
    engine = BookingEngine(BASE_DIR)
    cats = store.get_categories()
    category = cats.get(cat_key, cats.get("default", {}))
    target_rooms = category.get("rooms", category.get("ids", ["A-204"]))
    engine.book_chain(date_str, start_t, end_t, target_rooms)

def run_sync():
    from roombooker.calendar_sync import CalendarSync
    try:
        sync = CalendarSync(service_account_file=str(GOOGLE_CREDS))
        sync.sync_all()
    except Exception as e:
        print(f"[SYNC ERROR] {e}")

if __name__ == "__main__": pass
