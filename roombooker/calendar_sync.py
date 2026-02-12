import os
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from .config import CREDENTIALS_FILE

SCOPES = ['https://www.googleapis.com/auth/calendar']
TARGET_CALENDAR_ID = "3aa0292bb1019576073ee6521bdf7f12f1c795703be4cd02333217a809397b6e@group.calendar.google.com"

class CalendarSync:
    def __init__(self, service_account_file=None):
        self.creds_file = service_account_file or str(CREDENTIALS_FILE)
        self.calendar_id = TARGET_CALENDAR_ID
        self.service = None
        self._connect()

    def _connect(self):
        if not os.path.exists(self.creds_file):
            print(f"[SYNC] ⚠️ Credentials fehlen: {self.creds_file}")
            return
        try:
            creds = Credentials.from_service_account_file(self.creds_file, scopes=SCOPES)
            self.service = build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"[SYNC] Verbindungsfehler: {e}")

    def sync_scanned_bookings(self, bookings):
        if not self.service: return
        print(f"[SYNC] Synchronisiere {len(bookings)} gefundene Buchungen mit Google Calendar...")
        
        for b in bookings:
            try:
                # Datum Parsing (DD.MM.YYYY + HH:MM)
                d_obj = datetime.datetime.strptime(b['date'], "%d.%m.%Y")
                
                hm_start = b['start'].split(':')
                start_dt = d_obj.replace(hour=int(hm_start[0]), minute=int(hm_start[1]))
                
                hm_end = b['end'].split(':')
                end_dt = d_obj.replace(hour=int(hm_end[0]), minute=int(hm_end[1]))
                
                summary = f"Lernen: {b['room']}"
                desc = f"Account: {b['account']}"

                # Duplikat-Check
                events = self.service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=start_dt.isoformat() + "Z",
                    timeMax=(start_dt + datetime.timedelta(minutes=1)).isoformat() + "Z",
                    singleEvents=True
                ).execute()
                
                duplicate = False
                for e in events.get('items', []):
                    if b['room'] in e.get('summary', '') or summary == e.get('summary', ''):
                        duplicate = True
                        break
                
                if duplicate:
                    print(f"   -> Skip (Existiert): {summary}")
                    continue

                event = {
                    'summary': summary,
                    'location': 'Bibliothek vonRoll',
                    'description': desc,
                    'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
                    'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
                    'colorId': '5'
                }
                self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
                print(f"   -> ✅ Hinzugefügt: {summary}")
                
            except Exception as e:
                print(f"   [ERROR] Fehler bei {b}: {e}")
        
        print("[SYNC] Abgleich abgeschlossen.")
