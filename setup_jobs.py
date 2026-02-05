import json
import random
import sys
from pathlib import Path
from roombooker.server_logger import ServerLogger
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.browser import BookingWorker

# --- DEINE WUNSCHLISTE ---
# Das System sucht nach diesen Texten in den Raumnamen
TARGETS = ["D-204", "A-204", "A-241", "D-239", "D-231", "A-231", "D-202"]

def main():
    logger = ServerLogger()
    data_dir = resolve_data_dir()
    settings_path = data_dir / "settings.json"
    
    # 1. Accounts laden
    accs = load_accounts(settings_path)
    if not accs or not accs[0].email:
        print("❌ Keine Accounts gefunden.")
        sys.exit(1)

    print(f"--- Schritt 1: Scanne Räume mit {accs[0].email} ---")
    worker = BookingWorker(logger)
    worker.show_browser = False # Headless
    
    # Scan durchführen
    rooms_map = worker.update_room_list(accs[0].email, accs[0].password)
    
    if not rooms_map:
        print("❌ Scan fehlgeschlagen. Bitte Login/Passwort prüfen.")
        sys.exit(1)
        
    # Räume speichern (für Referenz)
    rooms_file = data_dir / "rooms.json"
    rooms_file.write_text(json.dumps(rooms_map, indent=2))
    print(f"✅ Scan erfolgreich! {len(rooms_map)} Räume gespeichert.")

    # 2. Wunschliste abgleichen
    print("\n--- Schritt 2: Erstelle smarte Job-Liste ---")
    
    # Wir suchen die echten Namen passend zu deinen Kürzeln
    found_rooms_ordered = []
    
    # Damit die Reihenfolge deiner Liste erhalten bleibt:
    for target in TARGETS:
        match = None
        for name in rooms_map.keys():
            if target in name:
                match = name
                break
        if match:
            if match not in found_rooms_ordered:
                found_rooms_ordered.append(match)
        else:
            print(f"⚠️ Warnung: Raum '{target}' nicht im System gefunden.")

    if not found_rooms_ordered:
        print("❌ Keine deiner Wunschräume wurde gefunden!")
        sys.exit(1)

    print(f"Gefundene Räume (Priorität Montag): {found_rooms_ordered}")

    # 3. Listen erstellen
    # Montag: Original Reihenfolge
    monday_list = list(found_rooms_ordered)
    
    # Freitag: Liste umdrehen (oder mischen), damit ein anderer Raum Prio 1 ist
    friday_list = list(found_rooms_ordered)
    # Wir rotieren die Liste um 3 Positionen, damit der Startraum sicher anders ist
    if len(friday_list) > 1:
        for _ in range(min(3, len(friday_list)-1)):
            friday_list.append(friday_list.pop(0))
            
    print(f"Gefundene Räume (Priorität Freitag): {friday_list}")

    # 4. Jobs.json bauen
    jobs = [
        {
            "active": True,
            "day": "Montag",
            "start": "10:00",
            "end": "18:00",
            "rooms": monday_list,
            "summary": "Lernen"
        },
        {
            "active": True,
            "day": "Freitag",
            "start": "10:00",
            "end": "18:00",
            "rooms": friday_list,
            "summary": "Lernen"
        }
    ]

    jobs_file = data_dir / "jobs.json"
    jobs_file.write_text(json.dumps(jobs, indent=2))
    print("\n✅ jobs.json erfolgreich erstellt!")
    print("Das System ist jetzt bereit. Der Container wird diese Jobs automatisch abarbeiten.")

if __name__ == "__main__":
    main()
