import os
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

class CalendarSync:
    def __init__(self, storage):
        self.storage = storage
        self.service = None
        self.calendar_id = 'primary'
        self.connect()

    def connect(self):
        try:
            SCOPES = ['https://www.googleapis.com/auth/calendar']
            creds = None
            token_path = self.storage.google_token
            creds_path = self.storage.google_creds

            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if creds_path.exists():
                        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                        creds = flow.run_local_server(port=0)
                    else:
                        print("[CALENDAR] Warnung: google_credentials.json fehlt.")
                        return
                
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())

            self.service = build('calendar', 'v3', credentials=creds)
            print("[CALENDAR] Verbunden ✅")
        except Exception as e:
            print(f"[CALENDAR] Init Fehler: {e}")

    def add_event(self, title, date_str, start_time, end_time, description=""):
        if not self.service: return
        try:
            # Datum parsen (DD.MM.YYYY -> YYYY-MM-DD)
            d_iso = datetime.datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
            start_dt = f"{d_iso}T{start_time}:00"
            end_dt = f"{d_iso}T{end_time}:00"
            
            # Duplikat-Check (Quick & Dirty: Suche Event am selben Tag zur selben Zeit)
            events_result = self.service.events().list(
                calendarId=self.calendar_id, 
                timeMin=f"{d_iso}T00:00:00Z", 
                timeMax=f"{d_iso}T23:59:59Z", 
                singleEvents=True
            ).execute()
            
            for e in events_result.get('items', []):
                # Wenn Titel und Startzeit übereinstimmen -> Skip
                if e['summary'] == title and e['start'].get('dateTime', '').startswith(start_dt[:16]):
                    print(f"[CALENDAR] Skip (Existiert schon): {title} @ {start_time}")
                    return

            event = {
                'summary': title,
                'description': description,
                'start': {'dateTime': start_dt, 'timeZone': 'Europe/Zurich'},
                'end': {'dateTime': end_dt, 'timeZone': 'Europe/Zurich'},
            }
            self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            print(f"[CALENDAR] + Event erstellt: {title} ({start_time}-{end_time})")
        except Exception as e:
            print(f"[CALENDAR ERROR] {e}")