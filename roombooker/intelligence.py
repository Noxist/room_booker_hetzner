import json
import os
from .config import load_weights, load_distance_matrix, get_excessive_logging

class Intelligence:
    def __init__(self):
        self.weights = load_weights()
        self.distance_matrix = load_distance_matrix()
        self.excessive_logging = get_excessive_logging()

    def t2m(self, t):
        """
        Convert time to minutes. Handles multiple formats:
        - "10" -> 600 (hours only)
        - "10:30" or "10.30" -> 630 (hours:minutes)
        - Integer < 24 -> treat as hours
        - Integer >= 60 -> treat as already minutes
        """
        try:
            if isinstance(t, int):
                return t * 60 if t < 24 else t
            t_str = str(t).replace(".", ":")
            parts = t_str.split(":")
            if len(parts) == 1:
                return int(parts[0]) * 60
            elif len(parts) == 2:
                h, m = map(int, parts)
                return h * 60 + m
            else:
                print(f"[WARNING] Invalid time format: {t}")
                return 0
        except Exception as e:
            print(f"[ERROR] Time parse failed for '{t}': {e}")
            return 0

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

    def _get_last_room(self, date_str, start_m, history_data):
        """Find the last room used before this slot on the same day."""
        day_bookings = history_data.get(date_str, [])
        last_room = None
        latest_end = -1
        for b in day_bookings:
            b_end = int(b['end'])
            if b_end <= start_m and b_end > latest_end:
                latest_end = b_end
                last_room = b.get('room')
        return last_room

    def _get_distance(self, room_a, room_b):
        """Get walking distance between two rooms from the distance matrix."""
        if not room_a or not room_b or not self.distance_matrix:
            return 0
        return self.distance_matrix.get(room_a, {}).get(room_b, 0)

    def score_room(self, room_name, start_m, end_m, date_str, history_data):
        """
        Score = (Duration * totalCoveredMin) + stabilityBonus - (Distance * 0.01)
        Uses last_room for distance lookup from roomDistanceMatrix.
        """
        duration = end_m - start_m
        w = self.weights

        # Base score: duration weighted
        score = duration * w.get("totalCoveredMin", 0.003)

        # Stability / Chaining bonus: same room continues a chain
        day_bookings = history_data.get(date_str, [])
        chaining = False
        for b in day_bookings:
            if b['room'] == room_name:
                if abs(int(b['end']) - start_m) <= 10 or abs(int(b['start']) - end_m) <= 10:
                    score += w.get("stabilityBonus", 0.5) * duration
                    chaining = True
                    break

        # Preferred room bonus
        if any(x in room_name for x in ["204", "206"]):
            score += w.get("preferredRoomBonus", 5)

        # Distance penalty: walk from last room
        last_room = self._get_last_room(date_str, start_m, history_data)
        distance = self._get_distance(last_room, room_name)
        distance_penalty = distance * 0.01
        score -= distance_penalty

        if self.excessive_logging:
            m2t = lambda m: f"{m//60:02d}:{m%60:02d}"
            print(f"    [SCORE] {room_name} | {m2t(start_m)}-{m2t(end_m)} | "
                  f"dur={duration}min | base={duration * w.get('totalCoveredMin', 0.003):.3f} | "
                  f"chain={'YES' if chaining else 'no'} | "
                  f"prefBonus={w.get('preferredRoomBonus', 5) if any(x in room_name for x in ['204','206']) else 0} | "
                  f"lastRoom={last_room} dist={distance}m pen=-{distance_penalty:.2f} | "
                  f"TOTAL={score:.3f}")

        return score

    def print_ascii_grid(self, date_str, history_data, opening_hours=None):
        """Print an ASCII grid of the day's bookings (excessive_logging only)."""
        if not self.excessive_logging:
            return

        day_bookings = history_data.get(date_str, [])
        if not day_bookings and not opening_hours:
            return

        oh_start = opening_hours[0] if opening_hours else 480  # 08:00
        oh_end = opening_hours[1] if opening_hours else 1260   # 21:00

        print(f"\n{'='*70}")
        print(f"  ASCII Grid for {date_str}")
        if opening_hours:
            print(f"  🕐 Opening Hours: {oh_start//60:02d}:{oh_start%60:02d} - {oh_end//60:02d}:{oh_end%60:02d}")
        print(f"{'='*70}")

        # Collect all rooms that have bookings
        rooms_in_use = sorted(set(b['room'] for b in day_bookings))
        if not rooms_in_use:
            print("  (no bookings)")
            print(f"{'='*70}\n")
            return

        # Header: hour labels
        hours = list(range(oh_start // 60, (oh_end // 60) + 1))
        header = "  Room     |"
        for h in hours:
            header += f"{h:02d}|"
        print(header)
        print("  " + "-" * (len(header) - 2))

        for room in rooms_in_use:
            line = f"  {room:<9}|"
            for h in hours:
                m_start = h * 60
                m_end = m_start + 60
                # Check if any booking covers this hour
                booked = False
                for b in day_bookings:
                    if b['room'] == room and int(b['start']) < m_end and int(b['end']) > m_start:
                        booked = True
                        break
                line += "██|" if booked else "  |"
            print(line)

        print(f"{'='*70}\n")
