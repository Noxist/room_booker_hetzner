from datetime import datetime, timedelta

class Intelligence:
    def calculate_needed_slots(self, start_time, end_time, rooms_state, last_scan):
        # Einfache Logik: Wenn nichts im Cache (last_scan) steht, brauchen wir den Slot.
        # Wir geben den Slot zurück, damit die Engine buchen kann.
        return [{
            "start": start_time,
            "end": end_time,
            "room": "Auto-Select", # Wird vom Browser gewählt
            "title": "Lernen"
        }]
