import sys
import os
from datetime import datetime, timedelta
import job_manager
import auto_booker
from roombooker.storage import load_rooms

def clean_time(t_str):
    return t_str.replace(".", ":").strip()

def interactive_wizard(mode="once"):
    print("\n" + "="*30)
    print(f"   WIZARD ({mode.upper()})")
    print("="*30)

    # 1. Datum
    default_date = datetime.now().strftime("%d.%m.%Y")
    if mode == "series":
        date_input = input(f"Start-Datum oder Wochentag (z.B. 'monday') [{default_date}]: ").strip() or default_date
    else:
        date_input = input(f"Datum (DD.MM.YYYY) [{default_date}]: ").strip() or default_date
    
    # 2. Zeit
    start = input("Start (HH:MM) [08:00]: ").strip() or "08:00"
    end = input("Ende  (HH:MM) [12:00]: ").strip() or "12:00"
    start, end = clean_time(start), clean_time(end)

    # 3. Kategorie
    print("\nKategorie:")
    print("  [1] Grosser Raum")
    print("  [2] Standard")
    print("  [3] Klein")
    cat_map = {"1": "large", "2": "standard", "3": "small"}
    c_choice = input("Wahl [2]: ").strip() or "2"
    category = cat_map.get(c_choice, "standard")

    # 4. Accounts
    accs = input("\nAnzahl Accounts (Enter='max'): ").strip() or "max"

    # Bestätigung
    print(f"\nPlan: {date_input} | {start}-{end} | {category}")
    if input("Ausführen/Speichern? (j/n) [j]: ").lower().strip() == "n":
        return

    # Logik
    if mode == "once":
        # Check ob Datum heute oder sehr nah -> Sofort ausführen
        # Einfachheitshalber: Wir legen einen Job an UND versuchen ihn sofort auszuführen
        job_id = job_manager.create_job(
            name=f"Manual {date_input}",
            date_str=date_input,
            start=start, end=end,
            category=category,
            accounts=accs,
            repetition="once"
        )
        print(f"Job {job_id} erstellt.")
        
        print("Starte Sofort-Buchung...")
        auto_booker.execute_job(date_input, start, end, category, accs)
        
    else:
        # Serie
        job_id = job_manager.create_job(
            name=f"Serie {date_input}",
            date_str=date_input,
            start=start, end=end,
            category=category,
            accounts=accs,
            repetition="weekly"
        )
        print(f"[SUCCESS] Serien-Job {job_id} gespeichert.")
        input("[Enter] weiter...")
