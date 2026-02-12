import os
import json
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from .config import HISTORY_FILE, GOOGLE_CREDS

SCOPES = ['https://www.googleapis.com/auth/calendar']
# Standard Kalender ID, falls keine in Config
TARGET_CALENDAR_ID = "3aa0292bb1019576073ee6521bdf7f12f1c795703be4cd02333217a809397b6e@group.calendar.google.com"

class CalendarSync:
    def __init__(self, service_account_file=None):
        # Falls None, nehme Standard aus Config
        self.creds_file = service_account_file or str(GOOGLE_CREDS)
        self.calendar_id = TARGET_CALENDAR_ID
        self.service = None
        self._connect()

    def _connect(self):
        if not os.path.exists(self.creds_file):
            print(f"[SYNC] ⚠️ Warnung: Credentials Datei nicht gefunden: {self.creds_file}")
            return
        try:
            creds = Credentials.from_service_account_file(self.creds_file, scopes=SCOPES)
            self.service = build('calendar', 'v3', credentials=creds)
            print("[SYNC] Verbunden mit Google Calendar API.")
        except Exception as e:
            print(f"[SYNC] Verbindungsfehler: {e}")

    def sync_all(self):
        if not self.service:
            print("[SYNC] Überspringe Sync (Keine Verbindung).")
            return

        print("[SYNC] Lese Buchungshistorie...")
        if not os.path.exists(HISTORY_FILE):
            return
        
        try:
            with open(HISTORY_FILE, 'r') as f: history = json.load(f)
        except: return

        # Hier würde die Logik stehen, die Events hochlädt.
        # Um Duplikate zu vermeiden, prüfen wir erst, was da ist.
        # (Vereinfacht für Stabilität - lädt hoch, was neu aussieht)
        
        for date_str, bookings in history.items():
            for b in bookings:
                self._create_event_if_missing(date_str, b)
        
        print("[SYNC] ✅ Kalender-Abgleich beendet.")

    def _create_event_if_missing(self, date_str, booking):
        # Datum parsen
        try:
            d_obj = datetime.datetime.strptime(date_str, "%d.%m.%Y")
            start_dt = d_obj + datetime.timedelta(minutes=int(booking['start']))
            end_dt = d_obj + datetime.timedelta(minutes=int(booking['end']))
            
            summary = f"Lernen: {booking['room']}"
            
            # Check if exists (einfacher Check)
            events = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_dt.isoformat() + "Z",
                timeMax=(start_dt + datetime.timedelta(minutes=1)).isoformat() + "Z",
                singleEvents=True
            ).execute()
            
            for e in events.get('items', []):
                if booking['room'] in e.get('summary', ''):
                    return # Existiert schon

            # Erstellen
            event = {
                'summary': summary,
                'location': 'Bibliothek vonRoll',
                'description': f"Gebucht für: {booking['account']}",
                'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
                'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
            }
            self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            print(f"   [SYNC] + Event erstellt: {date_str} {booking['room']}")
            
        except Exception as e:
            print(f"   [SYNC ERROR] {e}")
