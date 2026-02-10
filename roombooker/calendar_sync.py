from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

class CalendarSync:
    def __init__(self, service_account_file, calendar_id, logger=None):
        self.creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
        self.calendar_id = calendar_id
        self.service = build('calendar', 'v3', credentials=self.creds)
        self.logger = logger

    def sync_slots(self, slots):
        for slot in slots:
            print(f"[CALENDAR-MOCK] Würde Event erstellen für: {slot['room']}")
