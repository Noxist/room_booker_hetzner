from datetime import datetime

class BookingIntelligence:
    def __init__(self, storage):
        self.storage = storage
        self.weights = storage.get_weights()
        self.history = storage.get_history()

    def calculate_gaps(self, date_str, req_start_m, req_end_m):
        """Prüft History und gibt nur die Zeiten zurück, die noch NICHT gebucht sind."""
        day_history = self.history.get(date_str, [])
        booked_slots = sorted(day_history, key=lambda x: x['start'])
        
        gaps = []
        curr = req_start_m
        
        for b in booked_slots:
            # Slot liegt komplett vor curr
            if b['end'] <= curr: continue
            
            # Lücke gefunden
            if b['start'] > curr:
                end_of_gap = min(b['start'], req_end_m)
                if end_of_gap - curr >= 30: # Mindestens 30 min
                    gaps.append((curr, end_of_gap))
                curr = max(curr, b['end'])
            else:
                # Slot überlappt start
                curr = max(curr, b['end'])
            
            if curr >= req_end_m: break
            
        if curr < req_end_m:
            gaps.append((curr, req_end_m))
            
        return gaps

    def get_available_accounts(self, date_str, start_m, end_m, all_accounts):
        """Gibt Accounts zurück, die in diesem Zeitraum noch NICHTS gebucht haben."""
        day_history = self.history.get(date_str, [])
        blocked_emails = set()
        
        for h in day_history:
            # Wenn sich der gebuchte Slot mit dem Wunsch-Slot überschneidet
            if not (h['end'] <= start_m or h['start'] >= end_m):
                blocked_emails.add(h['account'])
        
        return [acc for acc in all_accounts if acc['email'] not in blocked_emails and acc.get('active', True)]

    def score_room(self, room_name, start_m, end_m, date_str):
        """Berechnet Score basierend auf weights.json"""
        duration = end_m - start_m
        score = duration * self.weights.get("totalCoveredMin", 0.001)
        
        # Room Stickiness: Bin ich heute schon in diesem Raum?
        day_history = self.history.get(date_str, [])
        for h in day_history:
            if h['room'] == room_name:
                score += self.weights.get("stabilityBonus", 0.5) * duration
                break
        
        # Preferred Rooms
        if any(fav in room_name for fav in ["206", "204"]):
            score += self.weights.get("preferredRoomBonus", 5)
            
        return score

    def record_booking(self, date_str, room, start_m, end_m, email):
        if date_str not in self.history: self.history[date_str] = []
        self.history[date_str].append({
            "room": room, "start": start_m, "end": end_m, "account": email, "timestamp": str(datetime.now())
        })
        self.storage.save_history(self.history)
