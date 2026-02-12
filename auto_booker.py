#!/usr/bin/env python3
import sys
import os

# Pfad sicherstellen
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from cli import interactive_wizard
from main import run_sync

def main():
    print("\n>>> ROOM BOOKER CLI <<<")
    print("1. Sofort-Buchung")
    print("2. Job erstellen (Serie)")
    print("3. Kalender Sync")
    print("4. Exit")
    
    choice = input("\nWahl [1]: ").strip() or "1"
    
    if choice == "1": interactive_wizard("once")
    elif choice == "2": interactive_wizard("series")
    elif choice == "3": run_sync()
    else: sys.exit(0)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\nAbbruch.")
