import sys
import argparse
from roombooker.storage import StorageManager
from roombooker.intelligence import BookingIntelligence
from roombooker.browser import BrowserEngine, m2t, t2m

def run_job(date_str, start_str, end_str, category, num_accounts):
    print(f"\n=== START JOB: {date_str} {start_str}-{end_str} ===")
    
    store = StorageManager()
    brain = BookingIntelligence(store)
    browser = BrowserEngine(headless=True)
    
    req_start = t2m(start_str)
    req_end = t2m(end_str)
    
    # 1. Gaps berechnen (Was fehlt noch?)
    gaps = brain.calculate_gaps(date_str, req_start, req_end)
    if not gaps:
        print("[INFO] Alles bereits abgedeckt! Keine Aktion nötig.")
        return

    print(f"[LOGIC] Zu buchende Lücken: {[f'{m2t(s)}-{m2t(e)}' for s,e in gaps]}")
    
    # 2. Scannen
    cats = store.get_categories()
    target_rooms = cats.get(category, cats.get("default", {})).get("rooms", [])
    if not target_rooms:
        print("[ERROR] Keine Ziel-Räume in categories.json definiert!")
        return
        
    print(f"[SCAN] Scanne Belegung für {len(target_rooms)} Räume...")
    rooms_state = browser.scan_grid(date_str, target_rooms)
    
    # 3. Planen & Buchen
    all_accounts = store.get_settings()
    if num_accounts > 0:
        all_accounts = all_accounts[:num_accounts]
        
    for g_start, g_end in gaps:
        curr = g_start
        while curr < g_end:
            # Wer kann buchen?
            avail_accs = brain.get_available_accounts(date_str, curr, g_end, all_accounts)
            if not avail_accs:
                print(f"[WARN] Keine Accounts mehr verfügbar für {m2t(curr)}!")
                break
                
            # Welcher Raum ist am besten? (Weights!)
            best_candidate = None
            
            for room, bookings in rooms_state.items():
                # Ist der Raum frei?
                # Einfache Prüfung: Überschneidet sich keine Buchung mit curr?
                # Wir suchen den längst möglichen Slot
                limit = g_end
                sorted_b = sorted(bookings, key=lambda x: x['start'])
                for b in sorted_b:
                    if b['end'] <= curr: continue
                    if b['start'] < limit: limit = b['start'] # Kollision
                
                actual_end = min(limit, curr + 240) # Max 4h pro Buchung
                
                if (actual_end - curr) >= 30: # Mindestens 30 min
                    score = brain.score_room(room, curr, actual_end, date_str)
                    if not best_candidate or score > best_candidate['score']:
                        best_candidate = {
                            "room": room, "start": curr, "end": actual_end, "score": score
                        }
            
            if not best_candidate:
                print(f"[WARN] Kein freier Raum ab {m2t(curr)} gefunden.")
                curr += 30 # Versuche später
                continue
                
            # Buchen
            acc = avail_accs[0] # Nimm den ersten verfügbaren
            print(f">>> BUCHE {best_candidate['room']} ({m2t(best_candidate['start'])}-{m2t(best_candidate['end'])}) mit {acc['email']}")
            
            if browser.perform_booking(date_str, best_candidate['room'], best_candidate['start'], best_candidate['end'], acc):
                print(f"    [SUCCESS] Gebucht!")
                brain.record_booking(date_str, best_candidate['room'], best_candidate['start'], best_candidate['end'], acc['email'])
                curr = best_candidate['end']
            else:
                print(f"    [FAIL] Fehlgeschlagen. Versuche nächsten Account...")
                # Temporär diesen Account aus Liste entfernen für diesen Loop wäre besser,
                # aber für V1 einfach weiter im Text
                avail_accs.pop(0)
                if not avail_accs:
                    print("    [ABORT] Alle Accounts durchprobiert.")
                    curr += 30

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="DD.MM.YYYY")
    parser.add_argument("start", help="HH:MM")
    parser.add_argument("end", help="HH:MM")
    parser.add_argument("category", help="default, quiet, etc.")
    parser.add_argument("accounts", type=int, help="Anzahl Accounts")
    
    if len(sys.argv) < 2:
        print("Usage: python3 main.py 20.02.2026 08:00 12:00 default 4")
        sys.exit(1)
        
    args = parser.parse_args()
    
    try:
        run_job(args.date, args.start, args.end, args.category, args.accounts)
    except KeyboardInterrupt:
        print("\n[ABORT] Durch Nutzer abgebrochen.")
