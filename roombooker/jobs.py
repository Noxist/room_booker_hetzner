import json
import os
import uuid
from datetime import datetime, timedelta
from .config import BASE_DIR

JOBS_FILE = BASE_DIR / "jobs.json"

class JobManager:
    def __init__(self):
        self.jobs = self.load_jobs()

    def load_jobs(self):
        if not JOBS_FILE.exists(): return []
        try:
            with open(JOBS_FILE, "r") as f: return json.load(f)
        except: return []

    def save_jobs(self):
        with open(JOBS_FILE, "w") as f: json.dump(self.jobs, f, indent=2)

    def add_job(self, job_type, target_date, time_start, time_end, category="default", frequency="onetime"):
        job = {
            "id": str(uuid.uuid4()),
            "type": job_type,           # "onetime" oder "recurring"
            "frequency": frequency,     # "daily", "weekly"
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
        """Findet Jobs, die heute/morgen fällig sind."""
        due = []
        today = datetime.now().date()
        
        for job in self.jobs:
            if not job.get("active", True): continue
            
            try:
                t_date = datetime.strptime(job["target_date"], "%d.%m.%Y").date()
                
                # Uni Bern Regel: Max 14 Tage im Voraus
                # Wir prüfen: Ist das Datum HEUTE oder in ZUKUNFT (bis +14 Tage)?
                days_diff = (t_date - today).days
                
                if 0 <= days_diff <= 14:
                    # Check ob schon gebucht für DIESES Datum
                    last = job.get("last_booked")
                    if last == job["target_date"]:
                        continue # Schon erledigt
                    
                    due.append((job, job["target_date"]))
            except: continue
            
        return due

    def mark_done(self, job_id, date_done):
        """Markiert Job als erledigt und rotiert Datum bei Wiederholung."""
        for job in self.jobs:
            if job["id"] == job_id:
                job["last_booked"] = date_done
                
                # Wiederholungs-Logik
                freq = job.get("frequency", "onetime")
                
                if freq == "weekly":
                    # Datum + 7 Tage
                    try:
                        old_date = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_date = old_date + timedelta(days=7)
                        job["target_date"] = new_date.strftime("%d.%m.%Y")
                        print(f"[JOB] Wöchentlicher Job rotiert auf: {job['target_date']}")
                    except: pass
                    
                elif freq == "daily":
                    # Datum + 1 Tag
                    try:
                        old_date = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_date = old_date + timedelta(days=1)
                        job["target_date"] = new_date.strftime("%d.%m.%Y")
                        print(f"[JOB] Täglicher Job rotiert auf: {job['target_date']}")
                    except: pass
                
                elif freq == "onetime":
                    job["active"] = False # Deaktivieren statt löschen
                
        self.save_jobs()
