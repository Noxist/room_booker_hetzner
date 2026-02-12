import json
import os
from .config import SETTINGS_FILE, HISTORY_FILE, WEIGHTS_FILE, CATEGORIES_FILE, ROOMS_FILE

class StorageManager:
    def _load(self, path, default=None):
        if default is None: default = {}
        if os.path.exists(path):
            try:
                with open(path, 'r') as f: return json.load(f)
            except: pass
        return default

    def _save(self, path, data):
        try:
            with open(path, 'w') as f: json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[STORAGE] Fehler beim Speichern von {path}: {e}")

    def get_settings(self):
        # Handhabt Liste vs Dictionary Format
        data = self._load(SETTINGS_FILE, [])
        if isinstance(data, dict): return data.get("accounts", [])
        return data

    def get_categories(self): return self._load(CATEGORIES_FILE, {})
    
    def add_to_history(self, date_str, room, start_m, end_m, account):
        history = self._load(HISTORY_FILE, {})
        if date_str not in history: history[date_str] = []
        
        # Duplikat-Check
        for b in history[date_str]:
            if b['room'] == room and b['start'] == int(start_m) and b['account'] == account:
                return # Schon drin
        
        history[date_str].append({
            "room": room,
            "start": int(start_m),
            "end": int(end_m),
            "account": account,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        self._save(HISTORY_FILE, history)
import time
