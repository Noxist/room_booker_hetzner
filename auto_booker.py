#!/usr/bin/env python3
import sys
import os
import warnings

# Nervige Google-Warnungen ignorieren
warnings.filterwarnings("ignore", category=FutureWarning)

# Pfad sicherstellen
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from cli import interactive_wizard
from main import run_sync

def main():
    # Force Flush, damit man sofort was sieht
    sys.stdout.reconfigure(line_buffering=True)
    
    print("\n>>> ROOM BOOKER CLI <<<")
    print("1. Sofort-Buchung")
    print("2. Job erstellen (Serie)")
    print("3. Kalender Sync")
    print("4. Exit")
    
    try:
        choice = input("\nWahl [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print("\nAbbruch.")
        return
    
    if choice == "1": interactive_wizard("once")
    elif choice == "2": interactive_wizard("series")
    elif choice == "3": run_sync()
    else: sys.exit(0)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\nAbbruch.")
