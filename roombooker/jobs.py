import json
import os
import uuid
from datetime import datetime, timedelta
from .config import JOBS_FILE

class JobManager:
    def __init__(self):
        self.jobs = self.load_jobs()

    def load_jobs(self):
        if not os.path.exists(JOBS_FILE): return []
        try:
            with open(JOBS_FILE, "r") as f: 
                data = json.load(f)
                return [j for j in data if 'id' in j]
        except: return []

    def save_jobs(self):
        with open(JOBS_FILE, "w") as f: json.dump(self.jobs, f, indent=2)

    def create_job(self, name, date_str, start, end, category, accounts, repetition="once"):
        new_job = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "target_date": date_str, # Einheitlichkeit: target_date vs date_str
            "date_str": date_str,    # Legacy support
            "start": start,
            "end": end,
            "category": category,
            "accounts": accounts,
            "frequency": repetition, # mapping repetition -> frequency
            "repetition": repetition,
            "active": True,
            "last_booked": None,
            "created_at": datetime.now().isoformat()
        }
        self.jobs.append(new_job)
        self.save_jobs()
        return new_job["id"]

    def mark_done(self, job_id, date_done):
        for job in self.jobs:
            if job.get("id") == job_id:
                job["last_booked"] = date_done
                freq = job.get("frequency", job.get("repetition", "once"))
                
                if freq == "weekly":
                    try:
                        d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_date = (d + timedelta(days=7)).strftime("%d.%m.%Y")
                        job["target_date"] = new_date
                        job["date_str"] = new_date
                    except: pass
                elif freq == "daily":
                    try:
                        d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_date = (d + timedelta(days=1)).strftime("%d.%m.%Y")
                        job["target_date"] = new_date
                        job["date_str"] = new_date
                    except: pass
                elif freq == "once" or freq == "onetime":
                    job["active"] = False
        self.save_jobs()
