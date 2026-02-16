import os
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from .config import CREDENTIALS_FILE
from .storage import StorageManager

SCOPES = ['https://www.googleapis.com/auth/calendar']
LOCATION = "Bibliothek vonRoll\nFabrikstrasse 8, 3012 Bern"

CATEGORY_LABELS = {
    "large": "Gross",
    "medium": "Mittel",
    "small": "Klein",
    "default": "Optimal",
}


class CalendarSync:
    def __init__(self, service_account_file=None):
        self.creds_file = service_account_file or str(CREDENTIALS_FILE)
        self.sm = StorageManager()
        self.calendar_id = self.sm.get_calendar_id()
        self.service = None
        self._connect()

    def _connect(self):
        if not os.path.exists(self.creds_file):
            print(f"[CAL] Credentials fehlen: {self.creds_file}")
            return
        try:
            creds = Credentials.from_service_account_file(self.creds_file, scopes=SCOPES)
            self.service = build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"[CAL] Verbindungsfehler: {e}")

    # ── helpers ──────────────────────────────────────────────

    def _m2t(self, minutes):
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _date_str_to_date(self, date_str):
        return datetime.datetime.strptime(date_str, "%d.%m.%Y").date()

    def _make_dt(self, date_str, minutes):
        d = self._date_str_to_date(date_str)
        return datetime.datetime.combine(d, datetime.time(minutes // 60, minutes % 60))

    def _build_title(self, label, existing_title=None):
        """Build title, preserving ' X' suffix if the user added it."""
        title = f"{label} (Lernen)"
        if existing_title and existing_title.rstrip().endswith(" X"):
            title += " X"
        return title

    def _find_events_by_property(self, key, value):
        if not self.service:
            return []
        try:
            result = self.service.events().list(
                calendarId=self.calendar_id,
                privateExtendedProperty=f"{key}={value}",
                singleEvents=True,
                maxResults=50,
            ).execute()
            return result.get('items', [])
        except Exception as e:
            print(f"[CAL] Suche fehlgeschlagen ({key}={value}): {e}")
            return []

    def _find_event_for_date(self, events, date_str):
        """From a list of events, find the one matching a specific date."""
        target = self._date_str_to_date(date_str)
        for ev in events:
            dt_str = ev.get('start', {}).get('dateTime', '')
            try:
                ev_date = datetime.datetime.fromisoformat(dt_str).date()
                if ev_date == target:
                    return ev
            except:
                pass
        return None

    # ── confirmed bookings ───────────────────────────────────

    def sync_booking(self, booking_id, date_str, room, start_m, end_m, account,
                     category_key="default", job_id=None):
        """Create or update a SINGLE merged calendar event for all bookings
        on the same date+job.  Instead of one event per gap, we consolidate
        into one event spanning the full booked range."""
        if not self.service:
            return

        # Collect ALL bookings for this date from history to build a merged view
        sm = StorageManager()
        history = sm.get_history()
        day_bookings = history.get(date_str, [])

        # Determine which bookings belong to this "group"
        # Group key: job_id (if set), otherwise category_key
        group_bookings = []
        for b in day_bookings:
            if job_id and b.get('job_id') == job_id:
                group_bookings.append(b)
            elif not job_id and b.get('category') == category_key and not b.get('job_id'):
                group_bookings.append(b)

        if not group_bookings:
            # Fallback: just use the current booking info
            group_bookings = [{
                'room': room, 'start': start_m, 'end': end_m,
                'account': account, 'id': booking_id,
            }]

        # Calculate merged time range
        merged_start = min(int(b['start']) for b in group_bookings)
        merged_end = max(int(b['end']) for b in group_bookings)

        # Build description with all segments
        desc_lines = []
        booking_ids = []
        rooms_used = set()
        for b in sorted(group_bookings, key=lambda x: int(x['start'])):
            bs, be = int(b['start']), int(b['end'])
            r = b.get('room', room)
            a = b.get('account', account)
            rooms_used.add(r)
            desc_lines.append(f"{self._m2t(bs)}-{self._m2t(be)}: {r} ({a})")
            if b.get('id'):
                booking_ids.append(b['id'])

        # Title: use room name if all same room, otherwise category label
        if len(rooms_used) == 1:
            title_base = list(rooms_used)[0]
        else:
            label = CATEGORY_LABELS.get(category_key, category_key.capitalize())
            title_base = label
        title = self._build_title(title_base)

        description = (
            f"Kategorie: {category_key}\n"
            + "\n".join(desc_lines)
            + (f"\nJob-ID: {job_id}" if job_id else "")
        )

        start_dt = self._make_dt(date_str, merged_start)
        end_dt = self._make_dt(date_str, merged_end)

        # Store first booking_id for reference; job_id is the main key
        primary_bid = booking_ids[0] if booking_ids else (booking_id or '')

        body = {
            'summary': title,
            'location': LOCATION,
            'description': description,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
            'transparency': 'transparent',
            'colorId': '9',
            'extendedProperties': {
                'private': {
                    'booking_id': primary_bid,
                    'job_id': job_id or '',
                    'source': 'roombooker',
                    'status': 'booked',
                }
            },
        }

        # Find existing event to update (avoid duplicates)
        existing = None
        if job_id:
            evs = self._find_events_by_property("job_id", job_id)
            existing = self._find_event_for_date(evs, date_str)
        if not existing:
            # Also search by any of the booking_ids
            for bid in booking_ids:
                evs = self._find_events_by_property("booking_id", bid)
                if evs:
                    existing = evs[0]
                    break

        try:
            if existing:
                # Delete any OTHER events for the same job+date (cleanup duplicates)
                if job_id:
                    all_evs = self._find_events_by_property("job_id", job_id)
                    for ev in all_evs:
                        if ev['id'] != existing['id']:
                            dt_str = ev.get('start', {}).get('dateTime', '')
                            try:
                                ev_date = datetime.datetime.fromisoformat(dt_str).date()
                                if ev_date == self._date_str_to_date(date_str):
                                    self.service.events().delete(
                                        calendarId=self.calendar_id, eventId=ev['id']
                                    ).execute()
                                    print(f"   [CAL] Duplikat entfernt: {ev.get('summary','?')}")
                            except:
                                pass

                self.service.events().update(
                    calendarId=self.calendar_id, eventId=existing['id'], body=body
                ).execute()
                print(f"   [CAL] Aktualisiert: {title} ({date_str} {self._m2t(merged_start)}-{self._m2t(merged_end)})")
            else:
                self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
                print(f"   [CAL] Erstellt: {title} ({date_str} {self._m2t(merged_start)}-{self._m2t(merged_end)})")
        except Exception as e:
            print(f"   [CAL ERROR] sync_booking: {e}")

    def delete_event_by_booking_id(self, booking_id):
        """Delete a calendar event by its booking_id."""
        if not self.service or not booking_id:
            return False
        try:
            events = self._find_events_by_property("booking_id", booking_id)
            for ev in events:
                self.service.events().delete(
                    calendarId=self.calendar_id, eventId=ev['id']
                ).execute()
                print(f"   [CAL] Event geloescht: {ev.get('summary', booking_id)}")
            return len(events) > 0
        except Exception as e:
            print(f"   [CAL ERROR] delete_event: {e}")
            return False

    # ── pending job placeholders ─────────────────────────────

    def sync_pending_job(self, job):
        """Create/update a placeholder event for a pending (unbooked) job."""
        if not self.service:
            return

        job_id = job.get('id')
        date_str = job.get('target_date') or job.get('date_str')
        start = job.get('start') or job.get('time_start', '08:00')
        end = job.get('end') or job.get('time_end', '12:00')
        category = job.get('category', 'default')

        if not date_str or not job_id:
            return

        from .utils import parse_time_to_minutes
        start_m = parse_time_to_minutes(start)
        end_m = parse_time_to_minutes(end)

        # Skip past dates
        try:
            if self._date_str_to_date(date_str) < datetime.date.today():
                return
        except:
            return

        # Find existing event for this job + date
        evs = self._find_events_by_property("job_id", job_id)
        existing = self._find_event_for_date(evs, date_str)
        existing_title = None

        if existing:
            # Don't overwrite a confirmed booking
            status = existing.get('extendedProperties', {}).get('private', {}).get('status', '')
            if status == 'booked':
                return
            existing_title = existing.get('summary', '')

        label = CATEGORY_LABELS.get(category, category.capitalize())
        title = self._build_title(label, existing_title)

        start_dt = self._make_dt(date_str, start_m)
        end_dt = self._make_dt(date_str, end_m)

        body = {
            'summary': title,
            'location': LOCATION,
            'description': f"Geplant: {label}\nKategorie: {category}\nJob-ID: {job_id}\nNoch nicht gebucht",
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
            'transparency': 'transparent',
            'colorId': '5',
            'extendedProperties': {
                'private': {
                    'job_id': job_id,
                    'source': 'roombooker',
                    'status': 'pending',
                }
            },
        }

        try:
            if existing:
                self.service.events().update(
                    calendarId=self.calendar_id, eventId=existing['id'], body=body
                ).execute()
                print(f"   [CAL] Placeholder aktualisiert: {title} ({date_str})")
            else:
                self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
                print(f"   [CAL] Placeholder erstellt: {title} ({date_str})")
        except Exception as e:
            print(f"   [CAL ERROR] sync_pending: {e}")

    def sync_pending_job_series(self, job, max_future_days=35):
        """For recurring jobs, create placeholder events for up to ~5 weeks ahead."""
        freq = job.get('repetition') or job.get('frequency', 'once')
        if freq in ('once', 'onetime'):
            self.sync_pending_job(job)
            return

        date_str = job.get('target_date') or job.get('date_str')
        if not date_str:
            return

        from datetime import timedelta
        try:
            current = datetime.datetime.strptime(date_str, "%d.%m.%Y").date()
        except:
            return
        end_date = datetime.date.today() + timedelta(days=max_future_days)

        while current <= end_date:
            # Skip Sundays (library closed)
            if current.weekday() != 6:
                job_copy = dict(job)
                job_copy['target_date'] = current.strftime("%d.%m.%Y")
                self.sync_pending_job(job_copy)

            if freq == 'daily':
                current += timedelta(days=1)
            elif freq == 'weekly':
                current += timedelta(weeks=1)
            elif freq == 'monthly':
                current += timedelta(days=30)
            elif freq == 'custom':
                interval = job.get('interval', 1)
                unit = job.get('interval_unit', 'weeks')
                if unit == 'days':
                    current += timedelta(days=interval)
                elif unit == 'weeks':
                    current += timedelta(weeks=interval)
                else:
                    current += timedelta(days=30 * interval)
            else:
                break

    def sync_all_pending_jobs(self):
        """Sync all active jobs (recurring → series, once → single)."""
        if not self.service:
            return
        from .jobs import JobManager
        jm = JobManager()
        active = [j for j in jm.jobs if j.get('active', True)]
        print(f"[CAL] Synchronisiere {len(active)} aktive Jobs als Kalender-Platzhalter...")
        for job in active:
            try:
                self.sync_pending_job_series(job)
            except Exception as e:
                print(f"   [CAL ERROR] Job {job.get('id')}: {e}")

    # ── fix existing events ──────────────────────────────────

    def fix_all_existing_events(self):
        """Patch ALL future events: transparency → transparent, location → full address."""
        if not self.service:
            return

        print("[CAL] Fixe alle bestehenden Events (Adresse, Frei/Belegt)...")
        now_iso = datetime.datetime.utcnow().isoformat() + 'Z'
        page_token = None
        fixed = 0

        while True:
            try:
                result = self.service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=now_iso,
                    maxResults=250,
                    singleEvents=True,
                    pageToken=page_token,
                ).execute()
            except Exception as e:
                print(f"[CAL ERROR] list: {e}")
                break

            for ev in result.get('items', []):
                patch = {}
                if ev.get('transparency') != 'transparent':
                    patch['transparency'] = 'transparent'
                if ev.get('location') != LOCATION:
                    patch['location'] = LOCATION
                if patch:
                    try:
                        self.service.events().patch(
                            calendarId=self.calendar_id,
                            eventId=ev['id'],
                            body=patch,
                        ).execute()
                        fixed += 1
                    except Exception as e:
                        print(f"   [CAL ERROR] patch {ev.get('summary','?')}: {e}")

            page_token = result.get('nextPageToken')
            if not page_token:
                break

        print(f"[CAL] {fixed} Events korrigiert")

    # ── legacy browser-scan sync ─────────────────────────────

    def sync_scanned_bookings(self, bookings):
        """Sync bookings discovered by the browser scan.
        Merges with existing roombooker events instead of creating duplicates."""
        if not self.service:
            return
        print(f"[CAL] Synchronisiere {len(bookings)} gescannte Buchungen...")

        for b in bookings:
            try:
                d_obj = datetime.datetime.strptime(b['date'], "%d.%m.%Y")
                hm_s = b['start'].split(':')
                start_dt = d_obj.replace(hour=int(hm_s[0]), minute=int(hm_s[1]))
                hm_e = b['end'].split(':')
                end_dt = d_obj.replace(hour=int(hm_e[0]), minute=int(hm_e[1]))

                summary = f"{b['room']} (Lernen)"

                # Check for existing events in this time window
                evts = self.service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=start_dt.isoformat() + "+01:00",
                    timeMax=(start_dt + datetime.timedelta(minutes=1)).isoformat() + "+01:00",
                    singleEvents=True,
                ).execute()

                dup = False
                for e in evts.get('items', []):
                    props = e.get('extendedProperties', {}).get('private', {})
                    # If it's a roombooker event for the same room, just patch it
                    if b['room'] in e.get('summary', '') or props.get('source') == 'roombooker':
                        self.service.events().patch(
                            calendarId=self.calendar_id,
                            eventId=e['id'],
                            body={'transparency': 'transparent', 'location': LOCATION},
                        ).execute()
                        dup = True
                        break
                if dup:
                    continue

                # No existing event — create one with proper properties
                event = {
                    'summary': summary,
                    'location': LOCATION,
                    'description': f"Account: {b['account']}\n(gescannt)",
                    'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
                    'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Europe/Zurich'},
                    'transparency': 'transparent',
                    'colorId': '9',
                    'extendedProperties': {
                        'private': {
                            'source': 'roombooker',
                            'status': 'booked',
                            'booking_id': '',
                            'job_id': '',
                        }
                    },
                }
                self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
                print(f"   -> Hinzugefuegt: {summary}")
            except Exception as e:
                print(f"   [CAL ERROR] {b}: {e}")
        print("[CAL] Abgleich abgeschlossen.")
