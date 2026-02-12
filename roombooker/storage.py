import json
import os
from .config import SETTINGS_FILE, HISTORY_FILE, CATEGORIES_FILE, JOBS_FILE, STATUS_FILE

class StorageManager:
    def _load(self, path, default):
        if path.exists():
            try:
                with open(path, "r") as f: return json.load(f)
            except: return default
        return default

    def _save(self, path, data):
        with open(path, "w") as f: json.dump(data, f, indent=2)

    def get_settings(self):
        # Lädt accounts.json oder settings.json
        data = self._load(SETTINGS_FILE, [])
        # Falls das Format {"accounts": [...]} ist, extrahieren
        if isinstance(data, dict): return data.get("accounts", [])
        return data if isinstance(data, list) else []

    def save_settings(self, accounts):
        # Preserve full settings structure if it exists
        current_data = self._load(SETTINGS_FILE, [])
        if isinstance(current_data, dict):
            # Preserve other fields, just update accounts
            current_data["accounts"] = accounts
            self._save(SETTINGS_FILE, current_data)
        else:
            # Just save accounts array
            self._save(SETTINGS_FILE, accounts)

    def get_categories(self): 
        return self._load(CATEGORIES_FILE, {"default": {"rooms": ["A-204"]}})

    def get_jobs(self):
        return self._load(JOBS_FILE, [])

    def save_jobs(self, jobs):
        self._save(JOBS_FILE, jobs)

    def get_history(self): return self._load(HISTORY_FILE, {})
    def save_history(self, history): self._save(HISTORY_FILE, history)

