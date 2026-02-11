import random
import time
from .browser import Browser
from .intelligence import Intelligence
from .utils import human_sleep

class BookingEngine:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.settings = []
        # WICHTIG: Das hier hat gefehlt, deshalb der Absturz in main.py
        self.browser = Browser(base_dir)
        self.intelligence = Intelligence()

    def book_slot(self, slot, date_str):
        if not self.settings:
            return False

        # Einfache Account-Auswahl (wie im Original)
        account = random.choice(self.settings)
        
        try:
            # Versucht die Buchung mit dem Browser durchzuführen
            return self.browser.perform_booking(account, date_str, slot)
        except Exception as e:
            print(f"[ENGINE] Fehler: {e}")
            return False
