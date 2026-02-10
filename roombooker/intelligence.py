import json
from .config import HISTORY_FILE, WEIGHTS_FILE

class BookingIntelligence:
    def __init__(self, storage):
        self.storage = storage
        self.weights = storage.get_weights()
        # Fallback Weights, falls Datei fehlt
        if not self.weights:
            self.weights = {
                "totalCoveredMin": 0.001,
                "preferredRoomBonus": 5,
                "vonRollBonus": 1
            }

    def print_debug_weights(self):
        print("\n[DEBUG] Weights (Entscheidungsgewichtung):")
        for k, v in self.weights.items():
            print(f"   - {k}: {v}")
        print("")

    def calculate_remaining_time(self, req_start, req_end, existing_bookings):
        """
        Berechnet NUR Zeitlücken basierend auf BEREITS GEBUCHTEN Terminen des Users.
        Das hat nichts mit Raumverfügbarkeit zu tun, sondern verhindert Doppelbuchungen des Users.
        """
        needed_slots = [(req_start, req_end)]
        blocked_intervals = []
        
        for b in existing_bookings:
            try:
                if ":" in str(b['start']):
                    h, m = map(int, b['start'].split(":")); s_min = h * 60 + m
                    h, m = map(int, b['end'].split(":")); e_min = h * 60 + m
                    blocked_intervals.append((s_min, e_min))
            except: continue
        
        blocked_intervals.sort()
        final_slots = []
        
        for n_start, n_end in needed_slots:
            cursor = n_start
            for b_start, b_end in blocked_intervals:
                if b_end <= cursor: continue
                if b_start >= n_end: break
                
                if b_start > cursor:
                    final_slots.append((cursor, b_start))
                cursor = max(cursor, b_end)
            
            if cursor < n_end:
                final_slots.append((cursor, n_end))
                
        return final_slots

    def calculate_gaps(self, date_str, start_m, end_m):
        # Splittet lange Slots in 4h Blöcke (Uni Limit)
        gaps = []
        curr = start_m
        while curr < end_m:
            next_hop = min(curr + 240, end_m)
            gaps.append((curr, next_hop))
            curr = next_hop
        return gaps

    def get_available_accounts(self, date_str, start_m, end_m, all_accounts):
        return list(all_accounts) 

    def score_room(self, room_name, start_m, end_m, date_str):
        duration = end_m - start_m
        score = duration * self.weights.get("totalCoveredMin", 0.001)
        if "206" in room_name or "204" in room_name: score += self.weights.get("preferredRoomBonus", 5)
        if room_name.startswith("A-"): score += self.weights.get("vonRollBonus", 1)
        return score

    def record_booking(self, date_str, room, start_m, end_m, account_email):
        hist = self.storage.get_history()
        if date_str not in hist: hist[date_str] = []
        hist[date_str].append({"room": room, "start": start_m, "end": end_m, "account": account_email})
        self.storage.save_history(hist)
