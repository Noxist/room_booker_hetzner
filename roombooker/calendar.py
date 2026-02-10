import os
import datetime
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

class CalendarSync:
    def __init__(self, storage):
        self.storage = storage
        self.service = None
        # Lade ID aus settings.json
        self.calendar_id = storage.get_calendar_id()
        print(f"[CALENDAR] Ziel-Kalender ID: {self.calendar_id}")
        self.connect()

    def connect(self):
        try:
            SCOPES = ['https://www.googleapis.com/auth/calendar']
            creds_path = self.storage.google_creds
            token_path = self.storage.google_token
            creds = None
            
            is_service_account = False
            if creds_path.exists():
                try:
                    with open(creds_path, 'r') as f:
                        info = json.load(f)
                        if info.get('type') == 'service_account':
                            is_service_account = True
                            creds = service_account.Credentials.from_service_account_file(
                                str(creds_path), scopes=SCOPES
                            )
                except: pass

            if not is_service_account:
                if token_path.exists():
                    try: creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
                    except: pass
                
                if not creds or not creds.valid:
                    if creds and creds.expired and creds.refresh_token:
                        try: creds.refresh(Request())
                        except: creds = None
                    if not creds and creds_path.exists():
                        print("[CALENDAR] Starte Login (Console)...")
                        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                        creds = flow.run_console()
                        with open(token_path, 'w') as token:
                            token.write(creds.to_json())

            if creds:
                self.service = build('calendar', 'v3', credentials=creds)
                print("[CALENDAR] Verbunden ✅")
            else:
                print("[CALENDAR] Keine Credentials gefunden.")

        except Exception as e:
            print(f"[CALENDAR] Init Fehler: {e}")

    def add_event(self, title, date_str, start_time, end_time, description=""):
        if not self.service: return False
        try:
            d_iso = datetime.datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
            start_dt = f"{d_iso}T{start_time}:00"
            end_dt = f"{d_iso}T{end_time}:00"
            
            events_result = self.service.events().list(
                calendarId=self.calendar_id, 
                timeMin=f"{d_iso}T00:00:00Z", 
                timeMax=f"{d_iso}T23:59:59Z", 
                singleEvents=True
            ).execute()
            
            for e in events_result.get('items', []):
                if e['summary'] == title and e['start'].get('dateTime', '').startswith(start_dt[:16]):
                    print(f"   -> Skip (Existiert): {title}")
                    return False

            event = {
                'summary': title,
                'description': description,
                'start': {'dateTime': start_dt, 'timeZone': 'Europe/Zurich'},
                'end': {'dateTime': end_dt, 'timeZone': 'Europe/Zurich'},
            }
            self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            print(f"   -> + Erstellt: {title} ({start_time}-{end_time})")
            return True
        except Exception as e:
            print(f"   [CAL ERROR] {e} (Evtl. Berechtigung prüfen!)")
            return False
