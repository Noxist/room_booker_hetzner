import sys, os, time
from datetime import datetime, timedelta
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from roombooker.storage import StorageManager
from main import run_booking_logic, run_sync

def wizard():
    print("\n" + "="*40 + "\n      ROOM BOOKER MASTER WIZARD 🧙‍♂️\n" + "="*40)
    print("1. Neue Buchung (Single/Serie)\n2. Manueller Kalender Sync\n3. Exit")
    choice = input("\nWahl [1]: ").strip() or "1"
    if choice == "2": run_sync(); return
    if choice == "3": return

    d_def = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    date_str = input(f"\nStart-Datum ({d_def}): ").strip() or d_def
    start_t = input("Start Zeit (08:00): ").strip() or "08:00"
    end_t = input("Ende Zeit (12:00): ").strip() or "12:00"
    
    sm = StorageManager()
    cats = sm.get_categories()
    cat_keys = list(cats.keys())
    print("\n--- 🏫 RAUM-KATEGORIE ---")
    for i, k in enumerate(cat_keys): print(f"{i+1}) {cats[k].get('title', k)}")
    cat_key = cat_keys[int(input(f"Wahl (1-{len(cat_keys)}) [2]: ").strip() or "2") - 1]

    print("\n--- 🔁 SERIEN-LOGIK ---")
    print("1. Einmalig\n2. Serie (Tage/Wochen/Monate)")
    if (input("Modus [1]: ") or "1") == "2":
        unit = input("Einheit (d=Tage, w=Wochen, m=Monate) [w]: ").lower() or "w"
        step = int(input(f"Alle wie viele {unit}? [1]: ") or "1")
        count = int(input("Anzahl Wiederholungen [4]: ") or "4")
        start_dt = datetime.strptime(date_str, "%d.%m.%Y")
        for i in range(count):
            if unit == "d": d = (start_dt + timedelta(days=i*step)).strftime("%d.%m.%Y")
            elif unit == "w": d = (start_dt + timedelta(weeks=i*step)).strftime("%d.%m.%Y")
            else: d = (start_dt + timedelta(days=i*step*30)).strftime("%d.%m.%Y")
            run_booking_logic(d, start_t, end_t, cat_key)
    else:
        run_booking_logic(date_str, start_t, end_t, cat_key)

if __name__ == "__main__":
    try: wizard()
    except KeyboardInterrupt: print("\nBye.")
