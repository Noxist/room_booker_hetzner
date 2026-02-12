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

    def create_job(self, name, date_str, start, end, category, accounts, repetition="once", interval=None, interval_unit=None):
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
            "created_at": datetime.now().isoformat()
        }
        
        # Add custom interval fields if provided
        if repetition == 'custom' and interval and interval_unit:
            new_job['interval'] = interval
            new_job['interval_unit'] = interval_unit
        
        self.jobs.append(new_job)
        self.save_jobs()
        return new_job["id"]

    def mark_done(self, job_id, date_done):
        for job in self.jobs:
            if job.get("id") == job_id:
                job["last_booked"] = date_done
                freq = job.get("repetition", job.get("frequency", "once"))
                
                if freq == "weekly":
                    try:
                        d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_d = (d + timedelta(days=7)).strftime("%d.%m.%Y")
                        job["target_date"] = new_d
                        job["date_str"] = new_d
                    except: pass
                elif freq == "daily":
                    try:
                        d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_d = (d + timedelta(days=1)).strftime("%d.%m.%Y")
                        job["target_date"] = new_d
                        job["date_str"] = new_d
                    except: pass
                elif freq == "monthly":
                    try:
                        from dateutil.relativedelta import relativedelta
                        d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_d = (d + relativedelta(months=1)).strftime("%d.%m.%Y")
                        job["target_date"] = new_d
                        job["date_str"] = new_d
                    except:
                        # Fallback: just add 30 days
                        try:
                            d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                            new_d = (d + timedelta(days=30)).strftime("%d.%m.%Y")
                            job["target_date"] = new_d
                            job["date_str"] = new_d
                        except: pass
                elif freq == "custom":
                    try:
                        d = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        interval = job.get("interval", 1)
                        unit = job.get("interval_unit", "weeks")
                        
                        if unit == "days":
                            new_d = (d + timedelta(days=interval)).strftime("%d.%m.%Y")
                        elif unit == "weeks":
                            new_d = (d + timedelta(weeks=interval)).strftime("%d.%m.%Y")
                        elif unit == "months":
                            try:
                                from dateutil.relativedelta import relativedelta
                                new_d = (d + relativedelta(months=interval)).strftime("%d.%m.%Y")
                            except:
                                new_d = (d + timedelta(days=30*interval)).strftime("%d.%m.%Y")
                        else:
                            new_d = job["target_date"]
                        
                        job["target_date"] = new_d
                        job["date_str"] = new_d
                    except: pass
                elif freq == "once" or freq == "onetime":
                    job["active"] = False
        self.save_jobs()
