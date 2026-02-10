import json
import os
from .config import SETTINGS_FILE, HISTORY_FILE, WEIGHTS_FILE, CATEGORIES_FILE

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
        data = self._load(SETTINGS_FILE, {"accounts": []})
        if isinstance(data, list): return data
        return data.get("accounts", [])

    def get_history(self): return self._load(HISTORY_FILE, {})
    def save_history(self, history): self._save(HISTORY_FILE, history)

    def get_weights(self):
        return self._load(WEIGHTS_FILE, {
            "totalCoveredMin": 0.001,
            "waitPenalty": -1.5,
            "switchBonus": -0.03,
            "stabilityBonus": 0.5,
            "preferredRoomBonus": 5
        })

    def get_categories(self): return self._load(CATEGORIES_FILE, {})
