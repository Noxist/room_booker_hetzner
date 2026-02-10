import os
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

# Deine Kalender-ID als Konstante
TARGET_CALENDAR_ID = "3aa0292bb1019576073ee6521bdf7f12f1c795703be4cd02333217a809397b6e@group.calendar.google.com"

class CalendarSync:
    def __init__(self, service_account_file, calendar_id=TARGET_CALENDAR_ID, logger=None):
        self.logger = logger
        self.calendar_id = calendar_id
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

    def _merge_slots(self, slots):
        """Fasst aufeinanderfolgende Buchungen zusammen."""
        if not slots: return []
        
        parsed_slots = []
        for s in slots:
            try:
                dt_start = datetime.datetime.strptime(f"{s['date']} {s['start']}", "%d.%m.%Y %H:%M")
                dt_end = datetime.datetime.strptime(f"{s['date']} {s['end']}", "%d.%m.%Y %H:%M")
                s['_dt_start'] = dt_start
                s['_dt_end'] = dt_end
                s['_accounts'] = {s.get('account', 'Unbekannt')} 
                parsed_slots.append(s)
            except: 
                print(f"[SKIP] Formatfehler bei: {s}")
                continue

        # Sortieren: Raum -> Startzeit
        parsed_slots.sort(key=lambda x: (x['room'], x['_dt_start']))

        merged = []
        if not parsed_slots: return []

        curr = parsed_slots[0]

        for next_s in parsed_slots[1:]:
            # Gleicher Raum und gleicher Tag?
            if (curr['room'] == next_s['room'] and 
                curr['_dt_start'].date() == next_s['_dt_start'].date()):
                
                # Check: Angrenzend oder Überlappend?
                if curr['_dt_end'] >= next_s['_dt_start']:
                    # Merge!
                    if next_s['_dt_end'] > curr['_dt_end']:
                        curr['_dt_end'] = next_s['_dt_end']
                    
                    curr['_accounts'].update(next_s['_accounts'])
                    continue

            merged.append(curr)
            curr = next_s
        
        merged.append(curr)
        return merged

    def sync_slots(self, raw_slots):
        if not self.service:
            print("[CAL-WARN] Kein Service verfügbar.")
            return

        merged_slots = self._merge_slots(raw_slots)
        print(f"[CAL-SYNC] {len(raw_slots)} Rohdaten -> {len(merged_slots)} Events nach Merge.")
        print(f"[CAL-SYNC] Ziel-Kalender: {self.calendar_id}")
        
        for slot in merged_slots:
            try:
                dt_start = slot['_dt_start']
                dt_end = slot['_dt_end']
                room = slot['room']
                acc_list = ", ".join(sorted(list(slot['_accounts'])))
                summary = f"{room} (Lernen)"

                # Duplikat-Check im ZIEL-KALENDER
                events = self.service.events().list(
                    calendarId=self.calendar_id, 
                    timeMin=dt_start.isoformat() + "Z", 
                    timeMax=(dt_start + datetime.timedelta(minutes=1)).isoformat() + "Z",
                    singleEvents=True
                ).execute()
                
                duplicate = False
                for e in events.get('items', []):
                    if room in e.get('summary', ''):
                        duplicate = True
                        break
                
                if duplicate:
                    print(f"   [SKIP] Event existiert schon: {room} {dt_start.strftime('%H:%M')}")
                    continue

                event_body = {
                    'summary': summary,
                    'location': 'Bibliothek vonRoll',
                    'description': f"Automatisches Booking.\nAccounts: {acc_list}",
                    'start': {'dateTime': dt_start.isoformat(), 'timeZone': 'Europe/Zurich'},
                    'end': {'dateTime': dt_end.isoformat(), 'timeZone': 'Europe/Zurich'},
                    'colorId': '5' 
                }
                
                self.service.events().insert(calendarId=self.calendar_id, body=event_body).execute()
                print(f"   [OK] Gesendet: {room} | {dt_start.strftime('%d.%m. %H:%M')} - {dt_end.strftime('%H:%M')}")

            except Exception as e:
                print(f"   [ERROR] Fehler bei Slot {slot.get('room')}: {e}")
