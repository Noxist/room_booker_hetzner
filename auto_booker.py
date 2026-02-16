#!/usr/bin/env python3
import sys
import os
import warnings

# Warnungen unterdrücken
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"

# Pfad sicherstellen
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# WICHTIG: Output sofort flushen (damit man was sieht trotz Warnungen)
sys.stdout.reconfigure(line_buffering=True)

from cli import interactive_wizard, deletion_wizard
from main import run_sync

def main():
    print("\n>>> ROOM BOOKER CLI <<<")
    print("1. Sofort-Buchung")
    print("2. Job erstellen (Serie)")
    print("3. Kalender Sync (Echtzeit)")
    print("4. Reservierung loeschen")
    print("5. Exit")
    
    try:
        choice = input("\nWahl [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print("\nAbbruch.")
        return
    
    if choice == "1": interactive_wizard("once")
    elif choice == "2": interactive_wizard("series")
    elif choice == "3": run_sync()
    elif choice == "4": deletion_wizard()
    else: sys.exit(0)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\nAbbruch.")
