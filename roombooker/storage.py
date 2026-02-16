import json
import uuid
import os
from datetime import datetime
from .config import SETTINGS_FILE, HISTORY_FILE, CATEGORIES_FILE, JOBS_FILE, STATUS_FILE


class StorageManager:
    def _load(self, path, default):
        if path.exists():
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return default
        return default

    def _save(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    # --- Accounts ---

    def get_settings(self):
        data = self._load(SETTINGS_FILE, [])
        if isinstance(data, dict):
            return data.get("accounts", [])
        return data if isinstance(data, list) else []

    def save_settings(self, accounts):
        current_data = self._load(SETTINGS_FILE, [])
        if isinstance(current_data, dict):
            current_data["accounts"] = accounts
            self._save(SETTINGS_FILE, current_data)
        else:
            self._save(SETTINGS_FILE, accounts)

    # --- Categories ---

    def get_categories(self):
        return self._load(CATEGORIES_FILE, {"default": {"rooms": ["A-204"]}})

    def save_categories(self, categories):
        self._save(CATEGORIES_FILE, categories)

    # --- Jobs ---

    def get_jobs(self):
        return self._load(JOBS_FILE, [])

    def save_jobs(self, jobs):
        self._save(JOBS_FILE, jobs)

    # --- Booking History ---

    def get_history(self):
        return self._load(HISTORY_FILE, {})

    def save_history(self, history):
        self._save(HISTORY_FILE, history)

    def add_to_history(self, date_str, room, start_m, end_m, email,
                       category="default", job_id=None):
        """
        Add a booking to history with unique ID. Returns the booking_id.
        If job_id is None, mark as manually created.
        """
        history = self.get_history()
        if date_str not in history:
            history[date_str] = []

        booking_id = str(uuid.uuid4())
        entry = {
            "id": booking_id,
            "room": room,
            "start": start_m,
            "end": end_m,
            "account": email,
            "category": category,
            "job_id": job_id,
            "manual": job_id is None,
            "timestamp": datetime.now().isoformat(),
        }
        history[date_str].append(entry)
        self.save_history(history)
        return booking_id

    # --- Calendar ---

    def get_calendar_id(self):
        data = self._load(SETTINGS_FILE, {})
        if isinstance(data, dict):
            return data.get("calendar_id", "primary")
        return "primary"

    # --- Account usage tracking ---

    def get_accounts_used_on_date(self, date_str):
        """Get set of account emails already used for bookings on a specific date."""
        history = self.get_history()
        return set(b.get('account', '') for b in history.get(date_str, []))

    def get_account_minutes_on_date(self, date_str, email):
        """Get total booked minutes for an account on a specific date."""
        history = self.get_history()
        total = 0
        for b in history.get(date_str, []):
            if b.get('account') == email:
                total += int(b.get('end', 0)) - int(b.get('start', 0))
        return total

    def get_room_category_size(self, room):
        """Get the size rank of a room based on categories. large=3, medium=2, small=1, unknown=0."""
        cats = self.get_categories()
        size_map = {"large": 3, "medium": 2, "small": 1}
        for cat_key, cat_data in cats.items():
            if room in cat_data.get("rooms", []):
                return size_map.get(cat_key, 0)
        return 0
