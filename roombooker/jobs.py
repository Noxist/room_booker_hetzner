import json
import uuid
import os
from datetime import datetime, timedelta
from .config import BASE_DIR

JOBS_FILE = BASE_DIR / "jobs.json"

class JobManager:
    def __init__(self):
        self._load()

    def _load(self):
        if JOBS_FILE.exists():
            try:
                with open(JOBS_FILE, "r") as f: self.jobs = json.load(f)
            except: self.jobs = []
        else:
            self.jobs = []

    def _save(self):
        with open(JOBS_FILE, "w") as f: json.dump(self.jobs, f, indent=2)

    def add_job(self, type, **kwargs):
        job = {
            "id": str(uuid.uuid4()),
            "type": type,
            "active": True,
            "last_booked": None,
            **kwargs
        }
        self.jobs.append(job)
        self._save()
        print(f"[JOBS] Job erstellt: {job}")

    def get_due_jobs(self):
        due = []
        today = datetime.now()
        max_future = today + timedelta(days=14)

        for job in self.jobs:
            if not job.get("active", True): continue
            
            target_date_str = job.get("target_date")
            if target_date_str:
                try:
                    d_parts = target_date_str.split(".")
                    dt_target = datetime(int(d_parts[2]), int(d_parts[1]), int(d_parts[0]))
                    
                    if dt_target.date() <= max_future.date():
                        if dt_target.date() < today.date():
                            job["active"] = False
                        elif job.get("last_booked") != target_date_str:
                            due.append((job, target_date_str))
                    else:
                        print(f"[SMART] Job {target_date_str} noch nicht im 14-Tage Fenster.")
                except:
                    print(f"[ERROR] Ungültiges Datumsformat im Job: {target_date_str}")

        self._save()
        return due
    
    def mark_done(self, job_id, date_str):
        for j in self.jobs:
            if j["id"] == job_id:
                j["last_booked"] = date_str
                if j["type"] == "onetime": j["active"] = False
        self._save()
