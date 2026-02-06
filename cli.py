import sys
import os
import json
import job_manager
import auto_booker
from datetime import datetime, timedelta

def load_categories():
    if os.path.exists("categories.json"):
        with open("categories.json", "r") as f: return json.load(f)
    return {}

def calculate_next_date(day_str_or_date):
    # Try parsing exact date
    try:
        dt = datetime.strptime(day_str_or_date, "%d.%m.%Y")
        return dt
    except ValueError:
        pass
    
    # Try parsing weekday (Monday, Tuesday...)
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_idx = -1
    for idx, d in enumerate(weekdays):
        if d in day_str_or_date.lower():
            day_idx = idx
            break
            
    if day_idx != -1:
        today = datetime.now()
        current_day = today.weekday()
        days_ahead = day_idx - current_day
        if days_ahead <= 0: days_ahead += 7
        return today + timedelta(days=days_ahead)
    
    return None

def parse_oneliner(cmd_str):
    # Format: DATE:TIME:CAT:ACCS:REP
    # Example: 22.02.2026:08:00-12:00:large:max:once
    parts = cmd_str.split(":")
    if len(parts) < 5:
        print("[ERROR] Invalid format. Use: DATE:START-END:CAT:ACCS:REP")
        return
    
    date_input = parts[0]
    time_range = parts[1].split("-")
    cat = parts[2]
    accs = parts[3]
    rep = parts[4] # once, weekly, daily, every.2.weeks
    
    # Interval parsing
    interval = 1
    rep_type = rep
    if "every." in rep:
        p = rep.split(".")
        try: interval = int(p[1])
        except: interval = 1
        rep_type = f"every_{p[2]}" # every_weeks, every_days
    elif rep == "weekly": rep_type = "weekly"
    elif rep == "daily": rep_type = "daily"
    elif rep == "monthly": rep_type = "monthly"
    
    # Date Calc
    target_dt = calculate_next_date(date_input)
    if not target_dt:
        print(f"[ERROR] Could not understand date: {date_input}")
        return

    date_str = target_dt.strftime("%d.%m.%Y")
    
    # Create Job
    job_id = job_manager.create_job(
        name=f"Book {date_str}",
        date_str=date_input, # Store original input for recurrence calc
        time_start=time_range[0],
        time_end=time_range[1],
        category=cat,
        accounts=accs,
        repetition=rep_type,
        interval=interval
    )
    print(f"[SUCCESS] Job created! ID: {job_id}")
    print(f"Target: {date_str} | Repetition: {rep_type} (Int: {interval})")

def run_scheduler():
    print("[SCHEDULER] Running check...")
    job_manager.cleanup_old_history()
    
    jobs = job_manager.list_jobs(active_only=True)
    today = datetime.now()
    
    for job in jobs:
        if job["status"] == "disabled": continue
        
        # Calculate Next Run Date
        base_date = calculate_next_date(job["target_date_str"])
        
        # Logic for recurrence (simplified for this step)
        # For ONCE jobs, base_date is the target.
        # For RECURRING, we need to find the next valid slot.
        
        target_run_date = base_date
        
        # 14 Day Logic
        delta = (target_run_date - today).days
        
        should_run = False
        
        if delta < 14:
            # Scenario B: Less than 14 days, just try it.
            should_run = True
            print(f"[CHECK] Job {job['id']} is close ({delta} days). Trying now.")
        elif delta == 14:
            # Perfect time
            should_run = True
            print(f"[CHECK] Job {job['id']} is exactly 14 days out. Executing.")
        else:
            print(f"[SKIP] Job {job['id']} is {delta} days away. Waiting.")
            
        if should_run:
            success = auto_booker.execute_job(
                target_run_date.strftime("%d.%m.%Y"),
                job["time_start"],
                job["time_end"],
                job["category"],
                job["accounts"]
            )
            
            if success:
                if job["repetition"] == "once":
                    job_manager.archive_job(job["id"], "success")
                else:
                    job_manager.update_recurring_run(job["id"])

def show_wizard():
    cats = load_categories()
    print("\n--- ROOM BOOKER CLI ---")
    print("Available Categories:")
    for k, v in cats.items():
        print(f"  [{k}] {v['title']} - {v['desc']}")
        
    print("\nCommands:")
    print("  book STRING   -> Create job (e.g. book Friday:08:00-12:00:large:max:weekly)")
    print("  list          -> Show active jobs")
    print("  disable ID    -> Pause a job")
    print("  enable ID     -> Resume a job")
    print("  run           -> Force scheduler run (Check 14 days)")
    
    cmd = input("\nCommand: ")
    parts = cmd.split(" ")
    action = parts[0]
    
    if action == "book":
        parse_oneliner(parts[1])
    elif action == "list":
        jobs = job_manager.list_jobs()
        print(json.dumps(jobs, indent=2))
    elif action == "disable":
        job_manager.toggle_job(parts[1], False)
        print("Job disabled.")
    elif action == "enable":
        job_manager.toggle_job(parts[1], True)
        print("Job enabled.")
    elif action == "run":
        run_scheduler()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Direct arguments handling
        if sys.argv[1] == "schedule": run_scheduler()
        elif sys.argv[1] == "book": parse_oneliner(sys.argv[2])
        else: show_wizard()
    else:
        show_wizard()
