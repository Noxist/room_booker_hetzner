import datetime
import os
from typing import Dict, List, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

class CalendarSync:
    def __init__(self, credentials_path: str, calendar_id: str, logger, summary: str = "Lernen"):
        self.creds = None
        self.logger = logger
        self.calendar_id = calendar_id
        self.summary = summary
        self.service = None
        self._auth(credentials_path)

    def _auth(self, creds_path):
        if os.path.exists("token.json"):
            try: self.creds = Credentials.from_authorized_user_file("token.json", SCOPES)
            except: pass
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try: self.creds.refresh(Request())
                except: self.creds = None
            if not self.creds and os.path.exists(creds_path):
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
            if self.creds:
                with open("token.json", "w") as token: token.write(self.creds.to_json())
        if self.creds:
            self.service = build("calendar", "v3", credentials=self.creds)
            self.logger.log(f"[CALENDAR] Verbunden ✅")

    def sync_slots(self, slots: List[Dict[str, object]]):
        if not self.service or not slots: return

        # Hole Events des Tages
        first_start = slots[0]['start']
        day_start = first_start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + datetime.timedelta(days=1)
        
        existing_events = []
        try:
            res = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=day_start.isoformat() + "Z",
                timeMax=day_end.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            existing_events = res.get("items", [])
        except Exception as e:
            self.logger.log(f"[CALENDAR] Fehler beim Laden existierender Events: {e}")

        count_new = 0
        for slot in slots:
            slot_acc = slot.get("account", "Unbekannt")
            merged = False
            for event in existing_events:
                if event.get("summary") != self.summary: continue
                
                # Check Room Match (Location or Description)
                loc_match = slot["room"] in event.get("location", "")
                desc_match = slot["room"] in event.get("description", "")
                if not (loc_match or desc_match): continue
                
                try:
                    evt_start = datetime.datetime.fromisoformat(event["start"]["dateTime"].replace('Z', '+00:00')).replace(tzinfo=None)
                    evt_end = datetime.datetime.fromisoformat(event["end"]["dateTime"].replace('Z', '+00:00')).replace(tzinfo=None)
                    s_start = slot["start"].replace(tzinfo=None)
                    s_end = slot["end"].replace(tzinfo=None)
                except: continue

                # Angrenzend oder Überlappend
                is_abutting = (abs((s_start - evt_end).total_seconds()) < 60) or (abs((s_end - evt_start).total_seconds()) < 60)
                is_overlapping = (s_start < evt_end) and (s_end > evt_start)
                
                if is_abutting or is_overlapping:
                    # MERGE!
                    new_start = min(evt_start, s_start)
                    new_end = max(evt_end, s_end)
                    
                    desc = event.get("description", "")
                    if slot_acc not in desc: desc += f", {slot_acc}"
                    
                    body = {
                        "summary": self.summary,
                        "location": slot["room"],
                        "description": desc,
                        "start": {"dateTime": new_start.isoformat(), "timeZone": "Europe/Zurich"},
                        "end": {"dateTime": new_end.isoformat(), "timeZone": "Europe/Zurich"},
                    }
                    try:
                        self.service.events().update(calendarId=self.calendar_id, eventId=event["id"], body=body).execute()
                        self.logger.log(f"-> VERBUNDEN: {slot['room']} ({new_start.strftime('%H:%M')}-{new_end.strftime('%H:%M')})")
                        event["start"]["dateTime"] = new_start.isoformat()
                        event["end"]["dateTime"] = new_end.isoformat()
                        event["description"] = desc
                        merged = True
                        break
                    except Exception as e:
                        self.logger.log(f"Fehler beim Mergen: {e}")

            if not merged:
                self.create_event(slot["start"], slot["end"], slot["room"], slot_acc)
                existing_events.append({
                    "id": "temp_id", "summary": self.summary, "location": slot["room"],
                    "description": f"Raum: {slot['room']}\nAccounts: {slot_acc}",
                    "start": {"dateTime": slot["start"].isoformat(), "timeZone": "Europe/Zurich"},
                    "end": {"dateTime": slot["end"].isoformat(), "timeZone": "Europe/Zurich"}
                })
                count_new += 1

        if count_new > 0:
            self.logger.log(f"[SYNC] {count_new} neue/aktualisierte Einträge.")

    def create_event(self, start_dt, end_dt, room, account):
        body = {
            "summary": self.summary,
            "location": room,
            "description": f"Raum: {room}\nAccounts: {account}",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Zurich"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Zurich"},
        }
        try:
            self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
            self.logger.log(f"-> + Erstellt: {room} ({start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')})")
        except Exception as e:
            self.logger.log(f"Fehler Create: {e}")
