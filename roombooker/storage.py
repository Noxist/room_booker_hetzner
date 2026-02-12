import json
import os
from .config import SETTINGS_FILE, HISTORY_FILE, WEIGHTS_FILE, CATEGORIES_FILE, ROOMS_FILE

class StorageManager:
    def _load(self, path, default=None):
        if os.path.exists(path):
            try:
                with open(path, 'r') as f: return json.load(f)
            except: pass
        return default if default is not None else {}

    def _save(self, path, data):
        with open(path, 'w') as f: json.dump(data, f, indent=2)

    def get_settings(self): return self._load(SETTINGS_FILE, [])
    def get_categories(self): return self._load(CATEGORIES_FILE, {})
    
    def add_to_history(self, date_str, room, start_m, end_m, account):
        history = self._load(HISTORY_FILE, {})
        if date_str not in history: history[date_str] = []
        history[date_str].append({
            "room": room,
            "start": int(start_m),
            "end": int(end_m),
            "account": account
        })
        self._save(HISTORY_FILE, history)
