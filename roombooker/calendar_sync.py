import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

class CalendarSync:
    def __init__(self, service_account_file, calendar_id="primary", logger=None):
        self.logger = logger
        if not os.path.exists(service_account_file):
            print(f"[CAL-ERROR] Credential Datei nicht gefunden: {service_account_file}")
            self.service = None
            return

        try:
            creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
            self.service = build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"[CAL-ERROR] Verbindung fehlgeschlagen: {e}")
            self.service = None

    def sync_slots(self, slots):
        if not self.service:
            print("[CAL-WARN] Kein Service, überspringe Sync.")
            return

        print(f"[CAL-SYNC] Synchronisiere {len(slots)} Events...")
        for s in slots:
            print(f"   -> Wäre gesendet an Google: {s['room']} ({s['start']})")
