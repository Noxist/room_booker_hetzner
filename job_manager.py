import json
import uuid
import os
from datetime import datetime
from roombooker.storage import load_jobs, resolve_data_dir, BlueprintStore

# Einfache Job-Verwaltung direkt über JSON-Dateien
DATA_DIR = resolve_data_dir()
JOBS_FILE = DATA_DIR / "jobs.json"

def load_all_jobs():
    if not JOBS_FILE.exists(): return []
    try:
        with open(JOBS_FILE, "r") as f: return json.load(f)
    except: return []

def save_jobs(jobs):
    with open(JOBS_FILE, "w") as f: json.dump(jobs, f, indent=2)

def create_job(name, date_str, start, end, category, accounts, repetition="once"):
    jobs = load_all_jobs()
    new_job = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "date_str": date_str,
        "start": start,
        "end": end,
        "category": category,
        "accounts": accounts,
        "repetition": repetition,
        "active": True,
        "created_at": datetime.now().isoformat()
    }
    jobs.append(new_job)
    save_jobs(jobs)
    return new_job["id"]

def print_queue():
    jobs = load_all_jobs()
    active_jobs = [j for j in jobs if j.get("active")]
    if not active_jobs:
        print("Keine aktiven Jobs in der Queue.")
    else:
        print(f"{'ID':<10} | {'Datum':<12} | {'Zeit':<11} | {'Name'}")
        print("-" * 50)
        for j in active_jobs:
            print(f"{j['id']:<10} | {j['date_str']:<12} | {j['start']}-{j['end']} | {j['name']}")

def interactive_menu():
    while True:
        print("\n--- JOB MANAGER ---")
        print("[l] Liste alle Jobs")
        print("[d] Lösche Job")
        print("[b] Zurück")
        c = input("Wahl: ").strip().lower()
        if c == 'b': break
        elif c == 'l': print_queue()
        elif c == 'd':
            jid = input("Job ID zum Löschen: ")
            jobs = load_all_jobs()
            jobs = [j for j in jobs if j['id'] != jid]
            save_jobs(jobs)
            print("Gelöscht.")
