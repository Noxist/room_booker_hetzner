import json
import os
import uuid
from datetime import datetime, timedelta
from .config import JOBS_FILE


class JobManager:
    def __init__(self):
        self.jobs = self.load_jobs()

    def load_jobs(self):
        if not os.path.exists(JOBS_FILE):
            return []
        try:
            with open(JOBS_FILE, "r") as f:
                data = json.load(f)
                return [j for j in data if 'id' in j]
        except Exception:
            return []

    def save_jobs(self):
        with open(JOBS_FILE, "w") as f:
            json.dump(self.jobs, f, indent=2)

    def create_job(self, name, date_str, start, end, category, accounts,
                   repetition="once", interval=None, interval_unit=None):
        """Create a new job. Normalizes time formats."""
        from .utils import smart_parse_time, normalize_date_str

        date_str = normalize_date_str(date_str)
        start = smart_parse_time(str(start))
        end = smart_parse_time(str(end))

        new_job = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "target_date": date_str,
            "date_str": date_str,
            "start": start,
            "time_start": start,
            "end": end,
            "time_end": end,
            "category": category,
            "accounts": accounts,
            "repetition": repetition,
            "frequency": repetition,
            "active": True,
            "last_booked": None,
            "created_at": datetime.now().isoformat(),
        }

        if repetition == 'custom' and interval and interval_unit:
            new_job['interval'] = interval
            new_job['interval_unit'] = interval_unit

        self.jobs.append(new_job)
        self.save_jobs()

        # Sync placeholder to Google Calendar
        try:
            from .config import CREDENTIALS_FILE
            if CREDENTIALS_FILE.exists():
                from .calendar_sync import CalendarSync
                cal = CalendarSync()
                cal.sync_pending_job_series(new_job)
        except Exception as e:
            print(f"[JOBS] Calendar-Sync fuer neuen Job fehlgeschlagen: {e}")

        return new_job["id"]

    def mark_done(self, job_id, date_done):
        """Mark a job as done for a date and advance target_date for recurring jobs."""
        for job in self.jobs:
            if job.get("id") != job_id:
                continue

            job["last_booked"] = date_done
            freq = job.get("repetition", job.get("frequency", "once"))

            if freq == "weekly":
                self._advance_date(job, timedelta(days=7))
            elif freq == "daily":
                self._advance_date(job, timedelta(days=1))
            elif freq == "monthly":
                self._advance_date_monthly(job, 1)
            elif freq == "custom":
                interval = job.get("interval", 1)
                unit = job.get("interval_unit", "weeks")
                if unit == "days":
                    self._advance_date(job, timedelta(days=interval))
                elif unit == "weeks":
                    self._advance_date(job, timedelta(weeks=interval))
                elif unit == "months":
                    self._advance_date_monthly(job, interval)
            elif freq in ("once", "onetime"):
                job["active"] = False

            # Sync next occurrence to calendar
            if job.get('active', False):
                try:
                    from .config import CREDENTIALS_FILE
                    if CREDENTIALS_FILE.exists():
                        from .calendar_sync import CalendarSync
                        cal = CalendarSync()
                        cal.sync_pending_job(job)
                except Exception as e:
                    print(f"[JOBS] Calendar-Sync nach mark_done fehlgeschlagen: {e}")

        self.save_jobs()

    def _advance_date(self, job, delta):
        """Advance target_date by a timedelta."""
        try:
            d = datetime.strptime(job["target_date"], "%d.%m.%Y")
            new_d = (d + delta).strftime("%d.%m.%Y")
            job["target_date"] = new_d
            job["date_str"] = new_d
        except Exception:
            pass

    def _advance_date_monthly(self, job, months):
        """Advance target_date by N months."""
        try:
            from dateutil.relativedelta import relativedelta
            d = datetime.strptime(job["target_date"], "%d.%m.%Y")
            new_d = (d + relativedelta(months=months)).strftime("%d.%m.%Y")
            job["target_date"] = new_d
            job["date_str"] = new_d
        except ImportError:
            # Fallback without dateutil
            try:
                d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                new_d = (d + timedelta(days=30 * months)).strftime("%d.%m.%Y")
                job["target_date"] = new_d
                job["date_str"] = new_d
            except Exception:
                pass
        except Exception:
            pass
