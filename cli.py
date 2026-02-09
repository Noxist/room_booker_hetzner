import sys
import os
import json
import job_manager
import auto_booker
from datetime import datetime, timedelta

def load_categories():
    if os.path.exists("categories.json"):
        with open("categories.json", "r") as f: return json.load(f)
    return {}

def calculate_next_date(day_str_or_date):
    try:
        dt = datetime.strptime(day_str_or_date, "%d.%m.%Y")
        return dt
    except ValueError:
        pass
    
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_idx = -1
    for idx, d in enumerate(weekdays):
        if d in day_str_or_date.lower():
            day_idx = idx
            break
            
    if day_idx != -1:
        today = datetime.now()
        current_day = today.weekday()
        days_ahead = day_idx - current_day
        if days_ahead <= 0: days_ahead += 7
        return today + timedelta(days=days_ahead)
    return None

def clean_time(t_str):
    return t_str.replace(".", ":")

def interactive_wizard():
    print("\n" + "="*30)
    print("   ROOM BOOKER WIZARD")
    print("="*30)

    # 1. Modus
    print("\nWas möchtest du tun?")
    print("  [1] Einmalige Buchung")
    print("  [2] Serie / Wiederkehrend")
    choice = input("Auswahl: ").strip()
    repetition = "weekly" if choice == "2" else "once"

    # 2. Datum
    default_date = datetime.now().strftime("%d.%m.%Y")
    date_input = input(f"\nDatum (DD.MM.YYYY) oder Wochentag [Standard: {default_date}]: ").strip() or default_date
    target_dt = calculate_next_date(date_input)
    if not target_dt:
        print("Fehler: Datum nicht erkannt.")
        return
    date_str = target_dt.strftime("%d.%m.%Y")

    # 3. Zeitraum
    print("\nZeitraum:")
    start = input("Start (HH:MM) [08:00]: ").strip() or "08:00"
    end = input("Ende  (HH:MM) [12:00]: ").strip() or "12:00"
    start, end = clean_time(start), clean_time(end)

    # 4. Kategorie
    cats = load_categories()
    print("\nRaum Kategorie:")
    cat_list = list(cats.keys())
    for i, c in enumerate(cat_list):
        print(f"  [{i+1}] {c.upper()}: {cats[c].get('title', '')}")
    
    cat_choice = input(f"Auswahl (1-{len(cat_list)}) [1]: ").strip() or "1"
    category = cat_list[int(cat_choice)-1]

    # 5. Accounts
    accs = input("\nAnzahl Accounts (Enter für 'max'): ").strip() or "max"

    # Zusammenfassung
    print("\n--- ZUSAMMENFASSUNG ---")
    print(f"Modus:   {repetition.capitalize()}")
    print(f"Ziel:    {date_str}")
    print(f"Zeit:    {start} - {end}")
    print(f"Raum:    {category}")
    print(f"Konten:  {accs}")

    confirm = input("\nJob erstellen? (j/n) [j]: ").lower().strip() or "j"
    if confirm != "j":
        print("Abbruch.")
        return

    # Job erstellen
    job_id = job_manager.create_job(
        name=f"Book {date_str}",
        date_str=date_input,
        time_start=start,
        time_end=end,
        category=category,
        accounts=accs,
        repetition=repetition,
        interval=1
    )
    print(f"\n[SUCCESS] Job erstellt! ID: {job_id}")

    # Sofort-Check: Wenn < 14 Tage, dann direkt ausführen
    delta = (target_dt - datetime.now()).days
    if delta < 14:
        print(f"Termin ist in {delta} Tagen. Starte Sofort-Buchung...")
        success = auto_booker.execute_job(date_str, start, end, category, accs)
        if success:
            print("✅ Buchung erfolgreich!")
            if repetition == "once":
                job_manager.archive_job(job_id, "success")
            else:
                job_manager.update_recurring_run(job_id)
        else:
            print("❌ Sofort-Buchung fehlgeschlagen (evtl. noch besetzt oder zu früh). Job bleibt aktiv.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "run": 
            # Deine existierende run_scheduler Logik hier einfügen oder aufrufen
            pass
    else:
        interactive_wizard()