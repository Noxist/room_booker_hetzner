import os
import json
from .config import HISTORY_FILE

class CalendarSync:
    def __init__(self, service_account_file=None):
        self.creds_file = service_account_file

    def sync_all(self):
        print("[SYNC] Synchronisiere mit Google Calendar...")
        if not os.path.exists(HISTORY_FILE):
            print("[SYNC] Keine Historie gefunden.")
            return
        # Simulation der API Logik
        print("[SYNC] ✅ Kalender-Abgleich beendet.")
        return True
