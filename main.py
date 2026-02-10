import sys
import argparse
import time
from datetime import datetime, timedelta
from roombooker.storage import StorageManager
from roombooker.intelligence import BookingIntelligence
from roombooker.browser import BrowserEngine, m2t, t2m
from roombooker.calendar import CalendarSync
from roombooker.jobs import JobManager

# --- HELPER ---
def select_category_interactive(storage):
    cats = storage.get_categories()
    if not cats: return "default"
    
    print("\nVerfügbare Kategorien:")
    keys = list(cats.keys())
    for idx, key in enumerate(keys):
        c = cats[key]
        print(f"[{idx+1}] {c.get('title', key)} ({c.get('desc', '')})")
    
    while True:
        choice = input("Wahl (Nummer): ").strip()
        if choice.isdigit():
            i = int(choice) - 1
            if 0 <= i < len(keys):
                return keys[i]
        print("Ungültige Auswahl.")

# --- CORE LOGIC (Booking) ---

def run_booking_process(date_str, start_time, end_time, category, num_accounts=4):
    """
    Führt den Buchungsprozess für ein spezifisches Datum aus.
    Dies ist die 'Worker'-Funktion, die vom Wizard und Runner genutzt wird.
    """
    print(f"\n>>> Starte Prozess für: {date_str} {start_time}-{end_time} [{category}]")
    
    storage = StorageManager()
    intel = BookingIntelligence(storage)
    cal = CalendarSync(storage)
    
    # 1. Gaps berechnen (Lokal)
    req_start = t2m(start_time)
    req_end = t2m(end_time)
    gaps = intel.calculate_gaps(date_str, req_start, req_end)
    
    if not gaps:
        print(f"[SKIP] {date_str} ist bereits lokal als 'gebucht' markiert (History Check). ✅")
        return True # Erfolgreich, da nichts zu tun

    print(f"[LOGIC] Zu buchen: {[f'{m2t(s)}-{m2t(e)}' for s,e in gaps]}")
    
    # 2. Browser Scan
    categories = storage.get_categories()
    target_rooms = categories.get(category, categories.get("default", {})).get("rooms", [])
    
    if not target_rooms:
        print("[ERROR] Keine Zielräume in categories.json definiert.")
        return False

    d_obj = datetime.strptime(date_str, "%d.%m.%Y")
    iso_date = d_obj.strftime("%Y-%m-%d")
    
    browser_eng = BrowserEngine(headless=True)
    
    # 2a. Live Scan der Räume
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        rooms_state = browser_eng.scan_available_rooms(browser, iso_date, target_rooms)
        browser.close()

    # Check: Wenn alles leer ist, ist der Tag wahrscheinlich noch zu (closed)
    total_slots = sum(len(v) for v in rooms_state.values())
    if total_slots == 0:
        print(f"[INFO] Scan lieferte 0 Slots. Tag ist vermutlich noch nicht freigeschaltet.")
        return False

    # 3. Booking Phase
    settings = storage.get_settings()
    all_accs = settings.get("accounts", [])
    if isinstance(num_accounts, int): all_accs = all_accs[:num_accounts]

    booking_made = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for gap_start, gap_end in gaps:
            current_time = gap_start
            while current_time < gap_end:
                # Accounts holen, die um diese Uhrzeit noch nichts haben
                avail_accs = intel.get_available_accounts(date_str, current_time, min(current_time+240, gap_end), all_accs)
                if not avail_accs: print("[WARN] Alle Accounts sind um diese Zeit schon belegt/blockiert."); break
                
                # Besten Raum berechnen
                best_slot = intel.find_best_slot(rooms_state, current_time, gap_end, date_str)
                if not best_slot: print("[WARN] Kein freier Raum gefunden."); break
                
                slot_filled = False
                for acc in avail_accs:
                    page = browser.new_page()
                    # Versuch zu buchen
                    if browser_eng.perform_booking(page, acc, best_slot, date_str):
                        print(f"[SUCCESS] {best_slot['room']} gebucht mit {acc['email']}!")
                        
                        # Speichern
                        intel.save_booking(date_str, best_slot['room'], best_slot['start'], best_slot['end'], acc['email'])
                        cal.add_event(f"Lernen: {best_slot['room']}", date_str, m2t(best_slot['start']), m2t(best_slot['end']), f"Account: {acc['email']}")
                        
                        current_time = best_slot['end']
                        slot_filled = True
                        booking_made = True
                        page.close()
                        break
                    else:
                        print(f"[FAIL] Buchung mit {acc['email']} fehlgeschlagen.")
                    page.close()
                
                if not slot_filled:
                    print("[ABORT] Konnte Lücke nicht füllen. Versuche nächsten Block...")
                    current_time += 30 
        browser.close()
        
    return booking_made

# --- RUNNER (CRONJOB) ---

def process_all_jobs():
    print(f"\n=== JOB RUNNER START: {datetime.now().strftime('%d.%m.%Y %H:%M')} ===")
    jm = JobManager()
    
    # 1. Smart Filter: Hol nur relevante Jobs
    due_items = jm.get_due_jobs()
    
    if not due_items:
        print("[INFO] Keine fälligen Jobs gefunden (14-Tage Regel aktiv). Beende.")
        return

    print(f"[INFO] {len(due_items)} Jobs sind fällig zur Prüfung.")
    
    for job, date_to_book in due_items:
        print(f"\n--- Processing Job {job['id']} für Datum {date_to_book} ---")
        
        success = run_booking_process(
            date_to_book, 
            job["time_start"], 
            job["time_end"], 
            job["category"]
        )
        
        if success:
            print(f"[JOB SUCCESS] Markiere Job als erledigt für {date_to_book}")
            jm.mark_executed(job["id"], date_to_book)
        else:
            print("[JOB INFO] Keine Buchung durchgeführt (Voll, Zu, oder Fehler).")
            
    print("\n=== JOB RUNNER ENDE ===")

# --- WIZARD UI ---

def wizard_add_job(recurring=False):
    jm = JobManager()
    storage = StorageManager()
    
    print("\n--- NEUEN JOB ANLEGEN ---")
    
    if recurring:
        print("Wochentage (Englisch: Mon, Tue, Wed, Thu, Fri, Sat, Sun)")
        days_in = input("Tage (kommagetrennt): ").strip().split(",")
        days = [d.strip().title()[:3] for d in days_in]
        target_date = None
        type = "recurring"
    else:
        print("Datum (Format DD.MM.YYYY, z.B. 25.03.2026)")
        target_date = input("Datum: ").strip()
        days = None
        type = "onetime"
        
    start = input("Startzeit (08:00): ") or "08:00"
    end = input("Endzeit (18:00): ") or "18:00"
    cat = select_category_interactive(storage)
    
    job = jm.add_job(type, start, end, cat, days, target_date)
    print("✅ Job gespeichert! Der Runner wird ihn automatisch aufgreifen, sobald das Datum im 14-Tage Fenster liegt.")

def manage_jobs():
    jm = JobManager()
    jobs = jm.get_active_jobs()
    if not jobs: print("Keine aktiven Jobs."); return
    
    print("\n--- JOB LISTE ---")
    for j in jobs:
        detail = f"Days: {j.get('days')}" if j['type'] == 'recurring' else f"Target: {j.get('target_date')}"
        last = j.get('last_booked') or "Nie"
        print(f"ID: {j['id']} | {j['type']} | {detail} | {j['time_start']}-{j['time_end']} | Last: {last}")
        
    act = input("\n[d] Löschen, [Enter] Zurück: ")
    if act == "d":
        jid = input("Job ID: ").strip()
        jm.delete_job(jid)

def manual_sync():
    print("\n=== MANUELLE SYNCHRONISATION ===")
    from roombooker.calendar import CalendarSync
    storage = StorageManager()
    cal = CalendarSync(storage)
    browser_eng = BrowserEngine(headless=True)
    accounts = storage.get_settings().get("accounts", [])
    
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for acc in accounts:
            if not acc.get("active", True): continue
            print(f">> Sync Account: {acc['email']}")
            page = browser.new_page()
            try:
                if browser_eng.login(page, acc['email'], acc['password']):
                    res = browser_eng.scan_user_reservations(page) 
                    print(f"   {len(res)} Buchungen gefunden.")
                    for r in res:
                        cal.add_event(f"Lernen: {r['room']}", r['date'], r['start'], r['end'], f"Sync {acc['email']}")
            except: pass
            finally: page.close()
        browser.close()
    print("Fertig.")

def start_wizard():
    while True:
        print("\n" + "="*35)
        print("   ROOM BOOKER WIZARD (V3 Modular)")
        print("="*35)
        print("[1] Einmalige Buchung (Sofort)")
        print("[2] Serie erstellen (Wochentage) -> jobs.json")
        print("[3] Zukünftige Buchung planen (Onetime) -> jobs.json")
        print("[4] Sync Google Cal")
        print("[5] Jobs verwalten")
        print("[q] Beenden")
        
        c = input("\nWahl: ").strip().lower()
        
        if c == "1":
            d_def = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
            date = input(f"Datum ({d_def}): ") or d_def
            start = input("Start (08:00): ") or "08:00"
            end = input("Ende (18:00): ") or "18:00"
            cat = select_category_interactive(StorageManager())
            run_booking_process(date, start, end, cat)
        elif c == "2": wizard_add_job(recurring=True)
        elif c == "3": wizard_add_job(recurring=False)
        elif c == "4": manual_sync()
        elif c == "5": manage_jobs()
        elif c == "q": sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-jobs", action="store_true", help="Führt fällige Jobs aus (Cron)")
    parser.add_argument("--interactive", action="store_true", help="Startet Wizard")
    args = parser.parse_args()

    if args.process_jobs:
        process_all_jobs()
    else:
        try: start_wizard()
        except KeyboardInterrupt: print("\nBye.")