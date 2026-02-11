import sys
import json
import time
import os
import argparse
from datetime import datetime, timedelta
from roombooker.storage import StorageManager
from roombooker.browser import BrowserEngine
from roombooker.config import SETTINGS_FILE

def t2m(t): 
    try: h,m=map(int,t.split(":")); return h*60+m
    except: return 0

def run_wizard():
    print("\n" + "="*30)
    print("   AUTO BOOKER WIZARD 🧙‍♂️")
    print("="*30)
    
    # Standardwerte berechnen
    d_def = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    
    # Eingaben abfragen
    print("\nBitte Buchungsdaten eingeben:")
    date_str = input(f"Datum ({d_def}): ").strip() or d_def
    start_t = input("Start (08:00): ").strip() or "08:00"
    end_t = input("Ende (12:00): ").strip() or "12:00"
    room = input("Raum (A-204): ").strip() or "A-204"
    
    print(f"\n[INFO] Lade Accounts...")
    sm = StorageManager()
    accounts = sm.get_settings()
    
    if not accounts:
        print("[ERROR] Keine Accounts in settings.json gefunden!")
        return

    print(f"[INFO] Starte Browser-Engine...")
    browser = BrowserEngine(headless=True)
    
    start_m = t2m(start_t)
    end_m = t2m(end_t)
    
    print(f"\n>>> Starte Buchungsversuch für {room} am {date_str} ({start_t}-{end_t})...")

    for acc in accounts:
        if not acc.get('active', True): continue
        
        email = acc['email']
        print(f"\n------------------------------------------------")
        print(f"Versuche Account: {email}")
        print(f"------------------------------------------------")
        
        # Aufruf der Browser-Logik
        success = browser.perform_booking(date_str, room, start_m, end_m, acc)
        
        if success:
            print(f"\n✅ BUCHUNG ERFOLGREICH MIT {email}!")
            return
        else:
            print(f"❌ Fehlgeschlagen mit {email}. Probiere nächsten...")

    print("\n[FAIL] Alle Accounts durchprobiert. Buchung nicht möglich.")

if __name__ == "__main__":
    try:
        run_wizard()
    except KeyboardInterrupt:
        print("\n[ABORT] Abbruch durch Benutzer.")
