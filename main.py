import sys
import argparse
import json
import os
import time
from datetime import datetime, timedelta
from roombooker.storage import StorageManager
from roombooker.intelligence import BookingIntelligence
from roombooker.browser import BrowserEngine, m2t, t2m
from roombooker.calendar_sync import CalendarSync 
from roombooker.jobs import JobManager
from roombooker.config import CREDENTIALS_FILE, BASE_DIR
from roombooker.utils import smart_parse_date, smart_parse_time

def append_to_cache(booking_data):
    """Schreibt eine neue Buchung sofort in die lokale last_scan.json."""
    cache_file = BASE_DIR / "last_scan.json"
    data = []
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f: data = json.load(f)
        except: pass
    
    # Füge neue Buchung hinzu
    data.append(booking_data)
    
    try:
        with open(cache_file, "w") as f: json.dump(data, f, indent=2)
        # print(f"[CACHE] Lokales Gedächtnis aktualisiert: {booking_data['time']}")
    except Exception as e:
        print(f"[CACHE ERROR] Konnte nicht speichern: {e}")

def load_cached_bookings(date_str):
    """Liest den Cache für ein bestimmtes Datum."""
    cache_file = BASE_DIR / "last_scan.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f: 
                all_cached = json.load(f)
                # Filter: Datum muss passen
                return [b for b in all_cached if b.get('date', '') == date_str]
        except: pass
    return []

def run_booking_logic(date_str, start_str, end_str, category, num_accounts, job_id=None):
    store = StorageManager()
    brain = BookingIntelligence(store)
    browser = BrowserEngine(headless=True)
    
    # Liste für den automatischen Kalender-Upload
    newly_booked_slots = []
    
    req_start = t2m(start_str)
    req_end = t2m(end_str)
    
    print(f"\n[LOGIC] Starte Planung für {date_str} ({start_str} - {end_str}) | Kat: {category}")
    
    # 1. LIVE-CHECK / CACHE
    existing_bookings = load_cached_bookings(date_str)
    
    # Wenn Cache komplett leer/fehlt -> Einmaliger Live-Sync zur Sicherheit
    if not existing_bookings and not (BASE_DIR / "last_scan.json").exists():
        print(f"[LOGIC] Kein Cache vorhanden. Hole einmalig aktuelle Reservationen...")
        all_accounts = store.get_settings()
        if all_accounts:
            browser.get_my_reservations(all_accounts[0])
            existing_bookings = load_cached_bookings(date_str)

    if existing_bookings:
        print(f"[LOGIC] {len(existing_bookings)} bestehende Buchungen im Cache gefunden.")
    else:
        print("[LOGIC] Keine Vorbuchungen im Cache (Tag gilt als frei).")

    # 2. Lücken berechnen (Gap Filling)
    needed_slots = brain.calculate_remaining_time(req_start, req_end, existing_bookings)
    
    if not needed_slots:
        print(f"[INFO] {date_str}: Alles bereits abgedeckt! ✅")
        if job_id: JobManager().mark_done(job_id, date_str)
        return

    # 3. Kategorie laden
    cats = store.get_categories()
    if category not in cats:
        print(f"[WARN] Kategorie '{category}' unbekannt. Nutze 'default'.")
        category = "default"
        
    cat_data = cats[category]
    target_rooms = cat_data.get("rooms", [])
    print(f"[SETUP] Modus: {cat_data.get('title')} ({len(target_rooms)} Räume)")

    # 4. Grid Scannen
    print(f"[SCAN] Scanne Verfügbarkeit im Buchungssystem...")
    rooms_state = browser.scan_grid(date_str, target_rooms)
    
    all_accounts = store.get_settings()
    if num_accounts > 0: all_accounts = all_accounts[:num_accounts]
    
    # 5. Planen & Buchen
    final_todos = []
    for n_start, n_end in needed_slots:
        sub_gaps = brain.calculate_gaps(date_str, n_start, n_end)
        for sub in sub_gaps: final_todos.append(sub)
    
    if not final_todos:
        print("[INFO] Keine offenen Slots zu buchen.")
        return

    print("\n" + "="*40)
    print(f"      PLANUNG: {len(final_todos)} Slots offen")
    print("="*40)

    account_index = 0
    
    for curr_start, curr_end in final_todos:
        curr = curr_start
        while curr < curr_end:
            best = None
            limit_search = curr_end
            
            for room, bookings in rooms_state.items():
                next_block = limit_search
                for b in sorted(bookings, key=lambda x: x['start']):
                    if b['end'] <= curr: continue
                    if b['start'] < next_block: next_block = b['start']
                
                actual_end = min(next_block, curr + 240)
                if (actual_end - curr) >= 30:
                    score = brain.score_room(room, curr, actual_end, date_str)
                    if not best or score > best['score']:
                        best = {"room": room, "start": curr, "end": actual_end, "score": score}
            
            if not best:
                print(f"   [SKIP] Kein Raum frei um {m2t(curr)}")
                curr += 30
                continue
            
            acc = all_accounts[account_index % len(all_accounts)]
            print(f">>> BUCHE {best['room']} ({m2t(best['start'])}-{m2t(best['end'])}) [{acc['email']}]")
            
            if browser.perform_booking(date_str, best['room'], best['start'], best['end'], acc):
                brain.record_booking(date_str, best['room'], best['start'], best['end'], acc['email'])
                
                # DATEN FÜR CACHE & CALENDAR VORBEREITEN
                slot_data = {
                    "date": date_str,
                    "start": m2t(best['start']),
                    "end": m2t(best['end']),
                    "room": best['room'],
                    "account": acc['email']
                }
                
                # 1. SOFORT IN DEN CACHE SCHREIBEN (Damit der nächste Run es weiß)
                append_to_cache(slot_data)
                
                # 2. Merken für Google Sync am Ende
                newly_booked_slots.append(slot_data)
                
                curr = best['end']
                account_index += 1 
            else:
                print("   [FAIL] Fehler. Nächster Account...")
                account_index += 1

    # 6. AUTO-SYNC ZU GOOGLE
    if newly_booked_slots:
        print("\n[AUTO-SYNC] Lade neue Buchungen in den Kalender hoch...")
        try:
            syncer = CalendarSync(str(CREDENTIALS_FILE))
            syncer.sync_slots(newly_booked_slots)
        except Exception as e:
            print(f"[SYNC ERROR] Upload fehlgeschlagen: {e}")

    if job_id: JobManager().mark_done(job_id, date_str)

def run_sync():
    # Beim manuellen Sync leeren wir den Cache und laden frisch
    cache_file = BASE_DIR / "last_scan.json"
    if cache_file.exists(): os.remove(cache_file)
    
    print("--- FULL SYNC START ---")
    store = StorageManager(); browser = BrowserEngine(headless=True)
    syncer = CalendarSync(str(CREDENTIALS_FILE))
    all_events = []
    for acc in store.get_settings():
        if not acc.get("active", True): continue
        print(f"[SYNC] Lade Reservationen für {acc['email']}...")
        all_events.extend(browser.get_my_reservations(acc))
    if all_events: syncer.sync_slots(all_events)
    print("--- SYNC DONE ---")

def start_wizard():
    print("\n--- ROOM BOOKER WIZARD (Instant Cache) ---")
    print("[1] Einmalige Buchung")
    print("[2] Zukünftige Buchung planen")
    print("[3] Jobs verwalten")
    print("[4] Manueller Full-Sync")
    print("[q] Beenden")
    
    c = input("Auswahl: ").strip()
    
    if c == "1" or c == "2":
        d_raw = input(f"Datum (Leer = Morgen): "); date_str = smart_parse_date(d_raw)
        s_raw = input("Start (z.B. 8, 8:30): "); start_str = smart_parse_time(s_raw)
        e_raw = input("Ende  (z.B. 16, 20): "); end_str = smart_parse_time(e_raw)
        
        print(f"-> {date_str} | {start_str} bis {end_str}")
        
        sm = StorageManager()
        cats = sm.get_categories()
        print("\nKategorien:")
        cat_keys = list(cats.keys())
        for idx, (key, val) in enumerate(cats.items()):
            print(f" [{idx+1}] {key.ljust(10)}: {val.get('title')}")
        
        k_raw = input(f"Wahl (1-{len(cats)}, Default=default): ").strip()
        category = "default"
        if k_raw.isdigit() and 0 < int(k_raw) <= len(cat_keys): category = cat_keys[int(k_raw)-1]
        elif k_raw in cat_keys: category = k_raw
            
        if c == "1":
            run_booking_logic(date_str, start_str, end_str, category, 4)
        else:
            JobManager().add_job("onetime", target_date=date_str, time_start=start_str, time_end=end_str, category=category)
            print("[OK] Job gespeichert.")

    elif c == "3":
        for j in JobManager().jobs: print(f"- {j['type']} {j.get('target_date')}")
    elif c == "4": run_sync()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--process-jobs", action="store_true")
    args = parser.parse_args()
    if args.process_jobs:
        jm = JobManager(); due = jm.get_due_jobs()
        for j, d in due: run_booking_logic(d, j['time_start'], j['time_end'], j['category'], 4, job_id=j["id"])
    else:
        try: start_wizard()
        except KeyboardInterrupt: print("\nAbbruch.")
