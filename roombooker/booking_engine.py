import random
from .browser import Browser
from .intelligence import Intelligence

class BookingEngine:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.settings = []
        self.browser = Browser(base_dir) 
        self.intelligence = Intelligence()

    def book_slot(self, slot, date_str):
        if not self.settings: return False
        account = random.choice(self.settings)
        try:
            return self.browser.perform_booking(account, date_str, slot)
        except Exception as e:
            print(f"[ENGINE] Fehler: {e}")
            return False
