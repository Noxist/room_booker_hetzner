from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Dict, Optional

@dataclass
class CalendarEvent:
    start: datetime
    end: datetime
    room: str


class CalendarSync:
    def __init__(self, credentials_path: str, calendar_id: str, logger, summary: str = "Lernen") -> None:
        self.credentials_path = credentials_path
        self.calendar_id = calendar_id
        self.logger = logger
        self.summary = summary

    @staticmethod
    def merge_slots(slots: Iterable[Dict[str, object]]) -> List[CalendarEvent]:
        grouped: Dict[str, List[CalendarEvent]] = {}
        for slot in slots:
            room = str(slot["room"])
            grouped.setdefault(room, []).append(
                CalendarEvent(start=slot["start"], end=slot["end"], room=room)
            )

        merged: List[CalendarEvent] = []
        for room, events in grouped.items():
            events.sort(key=lambda e: e.start)
            current: Optional[CalendarEvent] = None
            for event in events:
                if current is None:
                    current = CalendarEvent(start=event.start, end=event.end, room=room)
                    continue
                if event.start <= current.end:
                    current.end = max(current.end, event.end)
                else:
                    merged.append(current)
                    current = CalendarEvent(start=event.start, end=event.end, room=room)
            if current is not None:
                merged.append(current)
        merged.sort(key=lambda e: (e.start, e.room))
        return merged

    def _build_service(self):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/calendar"]
        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_path,
            scopes=scopes,
        )
        return build("calendar", "v3", credentials=credentials)

    def _event_payload(self, event: CalendarEvent) -> Dict[str, object]:
        return {
            "summary": self.summary,
            "location": "Fabrikstrasse 8, 3012 Bern",
            "description": f"Raum: {event.room}",
            "start": {"dateTime": event.start.isoformat(), "timeZone": "Europe/Zurich"},
            "end": {"dateTime": event.end.isoformat(), "timeZone": "Europe/Zurich"},
        }

    def sync_slots(self, slots: Iterable[Dict[str, object]]) -> None:
        merged = self.merge_slots(slots)
        if not merged:
            self.logger.log("Keine Slots zum Synchronisieren.")
            return

        service = self._build_service()
        for event in merged:
            payload = self._event_payload(event)
            self.logger.log(
                f"Sende Event: {event.start.strftime('%d.%m.%Y %H:%M')} - "
                f"{event.end.strftime('%H:%M')} ({event.room})"
            )
            service.events().insert(calendarId=self.calendar_id, body=payload).execute()
