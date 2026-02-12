from datetime import datetime
from roombooker.jobs import JobManager
from main import run_booking_logic

def clean_time(t_str):
    return t_str.replace(".", ":").strip()

def interactive_wizard(mode="once"):
    print("\n" + "="*30)
    print(f"   WIZARD ({mode.upper()})")
    print("="*30)

    d_def = datetime.now().strftime("%d.%m.%Y")
    date_input = input(f"Datum ({d_def}): ").strip() or d_def
    
    start = clean_time(input("Start (08:00): ").strip() or "08:00")
    end = clean_time(input("Ende  (12:00): ").strip() or "12:00")

    print("\nKategorie:")
    print("  [1] Grosser Raum (16 Pers.)")
    print("  [2] Standard (10 Pers.)")
    print("  [3] Klein (6 Pers.)")
    cat_map = {"1": "large", "2": "medium", "3": "small"}
    c = input("Wahl [2]: ").strip() or "2"
    category = cat_map.get(c, "medium")

    accs = 4

    if mode == "once":
        print(f"\n🚀 Starte Sofort-Buchung für {date_input} {start}-{end}...")
        run_booking_logic(date_input, start, end, category, accs)
    else:
        jm = JobManager()
        print("\nWiederholung:")
        print(" [1] Täglich")
        print(" [2] Wöchentlich")
        print(" [3] Monatlich")
        print(" [4] Benutzerdefiniert")
        f = input("Wahl [2]: ").strip() or "2"
        
        freq_map = {"1": "daily", "2": "weekly", "3": "monthly", "4": "custom"}
        freq = freq_map.get(f, "weekly")
        
        interval = 1
        interval_unit = "weeks"
        
        if freq == "custom":
            interval = int(input("Wiederhole alle X (Zahl): ").strip() or "1")
            print("Einheit:")
            print(" [1] Tage")
            print(" [2] Wochen")
            print(" [3] Monate")
            u = input("Wahl [2]: ").strip() or "2"
            unit_map = {"1": "days", "2": "weeks", "3": "months"}
            interval_unit = unit_map.get(u, "weeks")
        
        job_name = f"Serie {date_input} {start}-{end}"
        if freq == "custom":
            job_name = f"Alle {interval} {interval_unit}"
        
        job_id = jm.create_job(
            name=job_name, 
            date_str=date_input, 
            start=start, 
            end=end, 
            category=category, 
            accounts=accs, 
            repetition=freq,
            interval=interval if freq == "custom" else None,
            interval_unit=interval_unit if freq == "custom" else None
        )
        print(f"✅ Job gespeichert (ID: {job_id})")
        print(f"Nächster Termin: {date_input}")
        
        if input("\nErsten Termin sofort buchen? (y/n): ").lower() == "y":
            run_booking_logic(date_input, start, end, category, accs)
