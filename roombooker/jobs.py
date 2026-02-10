import json
import uuid
from datetime import datetime, timedelta
from .config import BASE_DIR

JOBS_FILE = BASE_DIR / "jobs.json"

class JobManager:
    def __init__(self):
        self._load()

    def _load(self):
        if JOBS_FILE.exists():
            with open(JOBS_FILE, "r") as f: self.jobs = json.load(f)
        else:
            self.jobs = []

    def _save(self):
        with open(JOBS_FILE, "w") as f: json.dump(self.jobs, f, indent=2)

    def add_job(self, type, **kwargs):
        job = {
            "id": str(uuid.uuid4()),
            "type": type, # "recurring" or "onetime"
            "active": True,
            "last_booked": None,
            **kwargs
        }
        self.jobs.append(job)
        self._save()
        print(f"[JOBS] Job erstellt: {job}")

    def get_due_jobs(self):
        """Gibt Jobs zurück, die HEUTE gebucht werden müssen (14-Tage-Fenster)."""
        due = []
        today = datetime.now()
        max_future = today + timedelta(days=14)

        for job in self.jobs:
            if not job.get("active", True): continue

            target_date_str = None
            
            if job["type"] == "onetime":
                target_date_str = job["target_date"]
            
            # (Recurring Logik vereinfacht für V1)
            
            # CHECK: Ist Datum im Zeitfenster?
            if target_date_str:
                d_parts = target_date_str.split(".")
                dt_target = datetime(int(d_parts[2]), int(d_parts[1]), int(d_parts[0]))
                
                if dt_target.date() <= max_future.date():
                    # Ist es in der Vergangenheit?
                    if dt_target.date() < today.date():
                        print(f"[JOBS] Job {target_date_str} ist abgelaufen.")
                        job["active"] = False
                    elif job.get("last_booked") != target_date_str:
                        due.append((job, target_date_str))
                else:
                    print(f"[SMART] Job für {target_date_str} noch nicht fällig (>14 Tage).")

        self._save()
        return due
    
    def mark_done(self, job_id, date_str):
        for j in self.jobs:
            if j["id"] == job_id:
                j["last_booked"] = date_str
                if j["type"] == "onetime": j["active"] = False
        self._save()
