import sys
from datetime import datetime
from roombooker.jobs import JobManager
from main import run_booking_logic

def clean_time(t_str):
    return t_str.replace(".", ":").strip()

def interactive_wizard(mode="once"):
    print("\n" + "="*30)
    print(f"   WIZARD ({mode.upper()})")
    print("="*30)

    # 1. Datum
    d_def = datetime.now().strftime("%d.%m.%Y")
    date_input = input(f"Datum ({d_def}): ").strip() or d_def
    
    # 2. Zeit
    start = clean_time(input("Start (08:00): ").strip() or "08:00")
    end = clean_time(input("Ende  (12:00): ").strip() or "12:00")

    # 3. Kategorie
    print("\nKategorie:")
    print("  [1] Grosser Raum (16P)")
    print("  [2] Standard (10P)")
    print("  [3] Klein (6P)")
    cat_map = {"1": "large", "2": "medium", "3": "small"}
    c = input("Wahl [2]: ").strip() or "2"
    category = cat_map.get(c, "medium")

    # 4. Accounts
    accs = 4 # Default max

    if mode == "once":
        print(f"\n🚀 Starte Sofort-Buchung...")
        run_booking_logic(date_input, start, end, category, accs)
    else:
        # Job anlegen
        jm = JobManager()
        freq_map = {"1": "daily", "2": "weekly", "3": "onetime"}
        print("\nWiederholung:")
        print(" [1] Täglich")
        print(" [2] Wöchentlich")
        f = input("Wahl [2]: ").strip() or "2"
        
        job_id = jm.create_job(
            name=f"Serie {date_input}", 
            date_str=date_input, 
            start=start, end=end, 
            category=category, 
            accounts=accs, 
            repetition=freq_map.get(f, "weekly")
        )
        print(f"✅ Job gespeichert (ID: {job_id})")
        
        if input("Ersten Termin sofort buchen? (y/n): ").lower() == "y":
            run_booking_logic(date_input, start, end, category, accs)
