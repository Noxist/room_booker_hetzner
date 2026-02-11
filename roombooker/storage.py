import json
import os
from .config import SETTINGS_FILE, HISTORY_FILE, WEIGHTS_FILE, CATEGORIES_FILE, ROOMS_FILE, APP_DIR

class StorageManager:
    def __init__(self):
        self.base_dir = APP_DIR
        self._ensure_files()

    def _ensure_files(self):
        for f in [SETTINGS_FILE, HISTORY_FILE, WEIGHTS_FILE, ROOMS_FILE]:
            if not os.path.exists(f):
                with open(f, 'w') as file: json.dump([], file)
        
        if not os.path.exists(CATEGORIES_FILE):
            default_cats = {
                "default": {"title": "Standard", "desc": "Egal", "ids": ["A-204", "A-206"], "min_duration": 60}
            }
            with open(CATEGORIES_FILE, 'w') as file: json.dump(default_cats, file)

    def get_settings(self):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                # FIX: Erkennt nun auch die Struktur { "accounts": [...] }
                if isinstance(data, dict) and "accounts" in data:
                    return data["accounts"]
                # Fallback für alte Struktur (direkte Liste)
                return data if isinstance(data, list) else []
        except: return []

    def save_settings(self, data):
        # Wir versuchen, die existierende Struktur beizubehalten
        try:
            current = {}
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict): current = loaded
            
            # Wenn die Datei vorher ein Dict war, speichern wir es wieder so
            if isinstance(current, dict) and "accounts" in current:
                current["accounts"] = data
                to_save = current
            else:
                # Sonst speichern wir einfach die Liste (Kompatibilitätsmodus)
                to_save = data
                
            with open(SETTINGS_FILE, 'w') as f: 
                json.dump(to_save, f, indent=2)
        except:
            # Notfall-Fallback
            with open(SETTINGS_FILE, 'w') as f: 
                json.dump(data, f, indent=2)

    def load_last_scan(self):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return []

    def get_categories(self):
        try:
            with open(CATEGORIES_FILE, 'r') as f: return json.load(f)
        except: return {}

    def get_rooms_by_category(self, cat_key):
        cats = self.get_categories()
        return cats.get(cat_key, {}).get("ids", [])
