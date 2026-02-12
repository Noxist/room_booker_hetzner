import random
import os
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
        history = self.sm._load(HISTORY_FILE, {})
        gaps = self.intelligence.calculate_needed_slots(start_t, end_t, date_str, history)
        
        if not gaps:
            print(f"[ENGINE] Keine Lücken für {date_str}. ✅")
            return True

        print(f"[ENGINE] Gefundene Gaps: {[f'{g[0]//60:02d}:{g[0]%60:02d}-{g[1]//60:02d}:{g[1]%60:02d}' for g in gaps]}")
        
        all_ok = True
        for g_s, g_e in gaps:
            scored = []
            for r in target_rooms:
                scored.append({"name": r, "score": self.intelligence.score_room(r, g_s, g_e, date_str, history)})
            
            scored.sort(key=lambda x: x['score'], reverse=True)
            
            gap_filled = False
            accounts = self.sm.get_settings()
            random.shuffle(accounts)

            for r_info in scored:
                if gap_filled: break
                for acc in accounts:
                    if not acc.get('active', True): continue
                    print(f"[ENGINE] Lücke {g_s}-{g_e}: Versuche {r_info['name']} (Score: {r_info['score']:.2f})")
                    if self.browser.perform_booking(date_str, r_info['name'], g_s, g_e, acc):
                        self.sm.add_to_history(date_str, r_info['name'], g_s, g_e, acc['email'])
                        history = self.sm._load(HISTORY_FILE, {}) # Reload
                        gap_filled = True
                        break
            if not gap_filled: all_ok = False
        return all_ok
