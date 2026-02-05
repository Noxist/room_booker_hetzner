import os
import sys
from roombooker.server_logger import ServerLogger
from roombooker.storage import load_accounts, RoomStore, resolve_data_dir
from roombooker.browser import BookingWorker

logger = ServerLogger()
data_dir = resolve_data_dir()
settings_path = data_dir / "settings.json"

print(f"Lade Accounts aus: {settings_path}")
accs = load_accounts(settings_path)

if not accs or not accs[0].email:
    print("❌ FEHLER: Keine gültigen Accounts in settings.json gefunden!")
    sys.exit(1)

print(f"Starte Scan mit Account: {accs[0].email}")

worker = BookingWorker(logger)
worker.show_browser = False # Headless erzwingen

try:
    rooms = worker.update_room_list(accs[0].email, accs[0].password)
    if rooms:
        RoomStore.save(rooms)
        print("\n✅ ERFOLG! Räume gespeichert.")
        for name in sorted(rooms.keys())[:15]:
            print(f'   - "{name}"')
    else:
        print("\n❌ Scan fehlgeschlagen: Login ok, aber keine Räume gefunden (Liste leer).")
except Exception as e:
    print(f"\n❌ CRITICAL ERROR: {e}")
