import json
import os
from .config import WEIGHTS_FILE

class Intelligence:
    def __init__(self):
        self.weights = self._load_weights()

    def _load_weights(self):
        if os.path.exists(WEIGHTS_FILE):
            try:
                with open(WEIGHTS_FILE, 'r') as f: return json.load(f)
            except: pass
        return {"totalCoveredMin": 0.003, "stabilityBonus": 0.5, "preferredRoomBonus": 5}

    def t2m(self, t):
        try:
            if isinstance(t, int): return t
            h, m = map(int, str(t).replace(".", ":").split(":"))
            return h * 60 + m
        except: return 0

    def calculate_needed_slots(self, start_time, end_time, date_str, history_data):
        """
        Berechnet Gaps. Wenn 8-12 gebucht ist und 10-14 angefragt wird -> Gap ist 12-14.
        """
        req_s = self.t2m(start_time)
        req_e = self.t2m(end_time)
        timeline = [False] * 1441
        
        day_bookings = history_data.get(date_str, [])
        for b in day_bookings:
            for m in range(int(b['start']), int(b['end'])):
                timeline[m] = True
        
        gaps = []
        start_gap = None
        for m in range(req_s, req_e):
            if not timeline[m]:
                if start_gap is None: start_gap = m
            else:
                if start_gap is not None:
                    if m - start_gap >= 30: gaps.append((start_gap, m))
                    start_gap = None
        if start_gap is not None and (req_e - start_gap) >= 30:
            gaps.append((start_gap, req_e))
        return gaps

    def score_room(self, room_name, start_m, end_m, date_str, history_data):
        """Bewertet Räume mit Chaining-Bonus (Stabilität)."""
        duration = end_m - start_m
        score = duration * self.weights.get("totalCoveredMin", 0.003)
        
        day_bookings = history_data.get(date_str, [])
        for b in day_bookings:
            if b['room'] == room_name:
                # Bonus wenn dieser Raum heute schon genutzt wurde (Chaining)
                if abs(int(b['end']) - start_m) <= 10 or abs(int(b['start']) - end_m) <= 10:
                    score += self.weights.get("stabilityBonus", 0.5) * duration
                    break
        
        if any(x in room_name for x in ["204", "206"]):
            score += self.weights.get("preferredRoomBonus", 5)
        return score
