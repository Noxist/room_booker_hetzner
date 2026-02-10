import sys
import os
import time

# Wir importieren die Module direkt, damit Fehler sofort sichtbar sind
import cli
import job_manager
import auto_booker
from roombooker.config import APP_NAME

def print_header():
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"--- {APP_NAME} ---")
    print("[1] Sofort Buchen")
    print("[2] Serie (Wochentage)")
    print("[3] Zukunft (Queue)")
    print("[4] Sync Google Cal")
    print("[5] Jobs verwalten")
    print("[q] Exit")

def main():
    while True:
        print_header()
        choice = input("\nWahl: ").strip().lower()
        
        if choice == '1':
            cli.interactive_wizard(mode="once")
        elif choice == '2':
            cli.interactive_wizard(mode="series")
        elif choice == '3':
            print("\n--- QUEUE (Nächste Jobs) ---")
            job_manager.print_queue()
            input("\n[Enter] zurück...")
        elif choice == '4':
            auto_booker.manual_sync_check()
            input("\n[Enter] zurück...")
        elif choice == '5':
            job_manager.interactive_menu()
        elif choice == 'q':
            print("Bye!")
            break

if __name__ == "__main__":
    main()
