import json
import os
import uuid
from datetime import datetime, timedelta
# Wir nutzen den Pfad aus der Environment Variable
DATA_DIR = os.getenv("ROOMBOOKER_DATA_DIR", "/root/auto_reserve_data")
JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")

class JobManager:
    def __init__(self):
        self.jobs = self.load_jobs()

    def load_jobs(self):
        if not os.path.exists(JOBS_FILE): return []
        try:
            with open(JOBS_FILE, "r") as f: 
                data = json.load(f)
                # Cleanup: Entferne kaputte Einträge ohne ID
                valid_jobs = []
                for j in data:
                    if 'id' in j: valid_jobs.append(j)
                return valid_jobs
        except: return []

    def save_jobs(self):
        with open(JOBS_FILE, "w") as f: json.dump(self.jobs, f, indent=2)

    def add_job(self, job_type, target_date, time_start, time_end, category="default", frequency="onetime"):
        job = {
            "id": str(uuid.uuid4()),
            "type": job_type,
            "frequency": frequency,
            "target_date": target_date,
            "time_start": time_start,
            "time_end": time_end,
            "category": category,
            "active": True,
            "last_booked": None
        }
        self.jobs.append(job)
        self.save_jobs()
        return job

    def get_due_jobs(self):
        due = []
        today = datetime.now().date()
        
        for job in self.jobs:
            if not job.get("active", True): continue
            # Sicherheitscheck
            if 'id' not in job: continue 

            try:
                t_date = datetime.strptime(job["target_date"], "%d.%m.%Y").date()
                days_diff = (t_date - today).days
                
                # Check: Ist Datum in Zukunft (<14 Tage) oder Heute?
                if 0 <= days_diff <= 14:
                    last = job.get("last_booked")
                    # Nur buchen wenn noch nicht für dieses Datum erledigt
                    if last != job["target_date"]:
                        due.append((job, job["target_date"]))
            except: continue
            
        return due

    def mark_done(self, job_id, date_done):
        found = False
        for job in self.jobs:
            # Safe access
            if job.get("id") == job_id:
                job["last_booked"] = date_done
                found = True
                
                freq = job.get("frequency", "onetime")
                if freq == "weekly":
                    try:
                        d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        job["target_date"] = (d + timedelta(days=7)).strftime("%d.%m.%Y")
                    except: pass
                elif freq == "daily":
                    try:
                        d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        job["target_date"] = (d + timedelta(days=1)).strftime("%d.%m.%Y")
                    except: pass
                elif freq == "onetime":
                    job["active"] = False
        
        if found: self.save_jobs()
