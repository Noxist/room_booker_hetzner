import random
from .browser import BrowserEngine
from .intelligence import Intelligence
from .storage import StorageManager
from .config import HISTORY_FILE

class BookingEngine:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.intelligence = Intelligence()
        self.browser = BrowserEngine(headless=True)
        self.sm = StorageManager()

    def book_chain(self, date_str, start_t, end_t, target_rooms):
        # Lade History via Storage Manager
        history = self.sm._load(HISTORY_FILE, {})
        
        # Berechne Lücken (Gaps)
        gaps = self.intelligence.calculate_needed_slots(start_t, end_t, date_str, history)
        
        if not gaps:
            print(f"[ENGINE] Keine Lücken für {date_str}. Alles erledigt! ✅")
            return True

        print(f"[ENGINE] Gefundene Gaps: {[f'{g[0]//60:02d}:{g[0]%60:02d}-{g[1]//60:02d}:{g[1]%60:02d}' for g in gaps]}")
        
        all_ok = True
        for g_s, g_e in gaps:
            # Räume bewerten (Scoring)
            scored = []
            for r in target_rooms:
                scored.append({"name": r, "score": self.intelligence.score_room(r, g_s, g_e, date_str, history)})
            
            # Sortieren nach Score (bester zuerst)
            scored.sort(key=lambda x: x['score'], reverse=True)
            
            gap_filled = False
            accounts = self.sm.get_settings()
            # Accounts mischen, aber "klug" (z.B. nicht die nehmen, die schon parallel gebucht haben)
            # Das macht intelligence.score_room indirekt über Kollisions-Prüfung in Zukunft
            random.shuffle(accounts)

            for r_info in scored:
                if gap_filled: break
                r_name = r_info['name']
                
                for acc in accounts:
                    if not acc.get('active', True): continue
                    
                    print(f"[ENGINE] Gap {g_s}-{g_e}: Versuche {r_name} (Score: {r_info['score']:.2f}) mit {acc['email']}")
                    
                    if self.browser.perform_booking(date_str, r_name, g_s, g_e, acc):
                        # Sofort speichern!
                        self.sm.add_to_history(date_str, r_name, g_s, g_e, acc['email'])
                        history = self.sm._load(HISTORY_FILE, {}) # Reload für nächsten Schritt
                        gap_filled = True
                        break
            
            if not gap_filled:
                print(f"[ENGINE] ❌ Konnte Gap {g_s}-{g_e} nicht füllen.")
                all_ok = False
                
        return all_ok
