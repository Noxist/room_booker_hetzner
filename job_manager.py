import json
import os
import time
import uuid
import shutil
from datetime import datetime, timedelta

DATA_DIR = "jobs"
ACTIVE_DIR = os.path.join(DATA_DIR, "active")
HISTORY_DIR = os.path.join(DATA_DIR, "history")

def ensure_dirs():
    os.makedirs(ACTIVE_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)

def create_job(name, date_str, time_start, time_end, category, accounts, repetition, interval=1):
    ensure_dirs()
    job_id = str(uuid.uuid4())[:8]
    job = {
        "id": job_id,
        "name": name or f"Job {job_id}",
        "created_at": datetime.now().isoformat(),
        "status": "active",
        "target_date_str": date_str, # Format DD.MM.YYYY or Weekday
        "time_start": time_start,
        "time_end": time_end,
        "category": category,
        "accounts": accounts,
        "repetition": repetition, # once, daily, weekly, monthly, every_x_days, every_x_weeks
        "interval": int(interval),
        "last_run": None
    }
    
    filename = os.path.join(ACTIVE_DIR, f"{job_id}.json")
    with open(filename, "w") as f:
        json.dump(job, f, indent=2)
    return job_id

def list_jobs(active_only=True):
    ensure_dirs()
    jobs = []
    target_dir = ACTIVE_DIR
    for f in os.listdir(target_dir):
        if f.endswith(".json"):
            try:
                with open(os.path.join(target_dir, f), "r") as file:
                    jobs.append(json.load(file))
            except: pass
    return jobs

def toggle_job(job_id, enable):
    path = os.path.join(ACTIVE_DIR, f"{job_id}.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        
        data["status"] = "active" if enable else "disabled"
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    return False

def archive_job(job_id, result_status):
    # Moves a ONCE job to history
    src = os.path.join(ACTIVE_DIR, f"{job_id}.json")
    dst = os.path.join(HISTORY_DIR, f"{job_id}_{int(time.time())}.json")
    
    if os.path.exists(src):
        with open(src, "r") as f:
            data = json.load(f)
        data["final_status"] = result_status
        data["archived_at"] = datetime.now().isoformat()
        
        with open(dst, "w") as f:
            json.dump(data, f, indent=2)
        os.remove(src)

def update_recurring_run(job_id):
    # Updates last_run for recurring jobs
    path = os.path.join(ACTIVE_DIR, f"{job_id}.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        data["last_run"] = datetime.now().isoformat()
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

def cleanup_old_history():
    # Deletes files older than 90 days in history
    ensure_dirs()
    cutoff = time.time() - (90 * 86400)
    
    count = 0
    for f in os.listdir(HISTORY_DIR):
        path = os.path.join(HISTORY_DIR, f)
        if os.path.isfile(path):
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                count += 1
    if count > 0:
        print(f"[CLEANUP] Deleted {count} old history files.")

