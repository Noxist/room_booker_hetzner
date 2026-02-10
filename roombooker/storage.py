import json
import os
from pathlib import Path

def resolve_data_dir():
    path = os.getenv("ROOMBOOKER_DATA_DIR", "./data")
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

class StorageManager:
    def __init__(self):
        self.data_dir = resolve_data_dir()
        self.history_path = self.data_dir / "booking_history.json"
        self.settings_path = self.data_dir / "settings.json"
        self.weights_path = self.data_dir / "weights.json"
        self.categories_path = self.data_dir / "categories.json"
        self.jobs_path = self.data_dir / "jobs.json"
        self.google_creds = self.data_dir / "google_credentials.json"
        self.google_token = self.data_dir / "token.json"

    def load_json(self, path, default=None):
        if path.exists():
            try:
                with open(path, "r") as f: return json.load(f)
            except json.JSONDecodeError: pass
        return default or {}

    def save_json(self, path, data):
        with open(path, "w") as f: json.dump(data, f, indent=2)

    def get_history(self): return self.load_json(self.history_path)
    def save_history(self, h): self.save_json(self.history_path, h)
    
    def get_settings(self): return self.load_json(self.settings_path)
    def get_weights(self): return self.load_json(self.weights_path)
    def get_categories(self): return self.load_json(self.categories_path)
    
    def get_jobs(self): return self.load_json(self.jobs_path, [])
    def add_job(self, job_data):
        jobs = self.get_jobs()
        jobs.append(job_data)
        self.save_json(self.jobs_path, jobs)
        print(f"[STORAGE] Job '{job_data.get('category')}' gespeichert.")
