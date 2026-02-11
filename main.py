import sys
import time
import argparse
import random
import json
import os
from roombooker.booking_engine import BookingEngine
from roombooker.storage import StorageManager
from roombooker.calendar_sync import CalendarSync
from roombooker.jobs import JobManager

# Helper für Web-Status (wird von app.py ausgelesen)
STATUS_FILE = os.path.join(os.getenv("ROOMBOOKER_DATA_DIR", "."), "web_status.txt")

def set_web_status(msg, state="info"):
    """Schreibt Status für die Webseite (info, success, error)"""
    try:
        with open(STATUS_FILE, "w") as f:
            f.write(f"{state}|{msg}")
    except: pass

def run_sync():
    set_web_status("Synchronisiere Kalender...", "info")
    print("[SYNC] Starte manuellen Sync...")
    try:
        CalendarSync().sync_all()
        print("[SYNC] Fertig.")
        set_web_status("Kalender synchronisiert ✅", "success")
    except Exception as e:
        print(f"[SYNC] Fehler: {e}")
        set_web_status(f"Sync Fehler: {e}", "error")

def check_overlap(start1, end1, start2, end2):
    """Gibt True zurück, wenn sich die Zeiten überlappen."""
    return max(start1, start2) < min(end1, end2)

def run_booking_logic(date_str, start_time, end_time, category_key, num_accounts, job_id=None):
    set_web_status(f"Analysiere Planung für {date_str}...", "info")
    print(f"\n[LOGIC] Starte Planung für {date_str} ({start_time} - {end_time}) | Kat: {category_key}")
    
    sm = StorageManager()
    settings = sm.get_settings()
    last_scan = sm.load_last_scan() # Wir laden den Cache!
    
    # --- SMART LOGIC: Accounts filtern ---
    available_accounts = []
    
    print(f"[LOGIC] Prüfe {len(settings)} Accounts gegen Cache ({len(last_scan)} Einträge)...")
    
    for acc in settings:
        email = acc['email']
        is_blocked = False
        
        for entry in last_scan:
            # Wenn Eintrag vom gleichen Account am gleichen Tag ist
            if entry.get('account') == email and entry.get('date') == date_str:
                # Prüfe Zeitüberlappung
                if check_overlap(start_time, end_time, entry['start'], entry['end']):
                    print(f"   -> Überlappung bei {email}: {entry['start']}-{entry['end']} ist belegt.")
                    is_blocked = True
                    break
        
        if not is_blocked:
            available_accounts.append(acc)
            
    if not available_accounts:
        msg = f"{date_str}: Alle Accounts sind um diese Zeit schon belegt! ❌"
        print(f"[LOGIC] {msg}")
        set_web_status(msg, "error")
        return

    print(f"[LOGIC] {len(available_accounts)} Accounts sind frei für diesen Slot.")
    
    # Engine starten mit gefilterten Accounts
    engine = BookingEngine(sm.base_dir)
    engine.settings = available_accounts # ÜBERSCHREIBEN mit smarter Liste
    
    # Scan
    set_web_status("Prüfe Raum-Verfügbarkeit...", "info")
    target_rooms = sm.get_rooms_by_category(category_key)
    rooms_state = engine.browser.scan_grid(date_str, target_rooms)
    
    # Entscheidung
    needed = engine.intelligence.calculate_needed_slots(start_time, end_time, rooms_state, last_scan)
    
    if not needed:
        msg = f"Alles bereits abgedeckt! ✅"
        print(f"[INFO] {date_str}: {msg}")
        set_web_status(msg, "success")
        
        # Job als erledigt markieren, auch wenn nichts gebucht wurde (weil schon voll)
        if job_id: JobManager().mark_done(job_id, date_str)
        return

    set_web_status(f"Versuche {len(needed)} Buchung(en)...", "info")
    
    # Buchen
    success_count = 0
    for slot in needed:
        # Hier nimmt er jetzt automatisch den nächsten FREIEN Account aus unserer Smart-Liste
        if engine.book_slot(slot, date_str):
            success_count += 1
            set_web_status(f"Gebucht: {slot['room']} ({slot['start']}-{slot['end']}) ✅", "success")
    
    if success_count > 0:
        # Job Update
        if job_id: JobManager().mark_done(job_id, date_str)
        
        # Sync
        print("\n[AUTO-SYNC] Lade neue Buchungen in den Kalender hoch...")
        set_web_status("Aktualisiere Kalender...", "info")
        CalendarSync().sync_all()
        set_web_status(f"Fertig! {success_count} Buchungen erstellt. ✅", "success")
    else:
        set_web_status("Keine Buchung möglich (Fehler oder voll). ❌", "error")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-jobs", action="store_true")
    args = parser.parse_args()

    if args.process_jobs:
        # CLI Mode (Cronjob)
        pass
