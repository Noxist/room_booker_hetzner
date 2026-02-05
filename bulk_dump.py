import os
import time
import sys
from datetime import date, timedelta, datetime
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir

# --- KONFIGURATION ---
START_DATE = date(2026, 1, 2)  # 02.01.2026
END_DATE = date(2026, 2, 8)    # 08.02.2026
OUTPUT_DIR = "/app/html_dumps"

def run_bulk_dump():
    print(f"--- 📦 BULK DUMP START: {START_DATE} bis {END_DATE} ---")
    
    # Ordner erstellen
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    data_dir = resolve_data_dir()
    accs = load_accounts(data_dir / "settings.json")
    session_files = list(data_dir.glob("session_*.json"))
    session_path = session_files[0] if session_files else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Wir nutzen einen großen Viewport, damit alle Events gerendert werden
        context = browser.new_context(storage_state=str(session_path)) if session_path else browser.new_context()
        page = context.new_page()

        # Login Check (Einmalig am Anfang)
        try:
            print("🔑 Prüfe Login...")
            page.goto("https://raumreservation.ub.unibe.ch/event/add")
            time.sleep(2)
            
            if "login" in page.url or "wayf" in page.url:
                print("⚠️ Logge ein...")
                if accs:
                    page.fill("#username", accs[0].email)
                    page.keyboard.press("Enter")
                    time.sleep(2)
                    page.fill("#password", accs[0].password)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("networkidle")
                    # Session speichern
                    new_session = data_dir / f"session_{accs[0].email.replace('@','_')}.json"
                    context.storage_state(path=str(new_session))
            
            # Standort Fix (Einmalig)
            print("📍 Setze Standort auf vonRoll...")
            page.goto("https://raumreservation.ub.unibe.ch/set/1")
            time.sleep(1)

        except Exception as e:
            print(f"❌ Fehler beim Init: {e}")
            return

        # --- LOOP DURCH DIE TAGE ---
        delta = END_DATE - START_DATE
        
        for i in range(delta.days + 1):
            current_day = START_DATE + timedelta(days=i)
            day_str = current_day.strftime("%d.%m.%Y")
            iso_date = current_day.strftime("%Y-%m-%d")
            filename = f"{iso_date}_dump.html"
            filepath = os.path.join(OUTPUT_DIR, filename)

            print(f"[{i+1}/{delta.days + 1}] Lade {day_str} ...", end="", flush=True)

            try:
                target_url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
                page.goto(target_url)
                
                # Wichtig: Warten bis die SVG-Elemente (Buchungen) da sind
                # Wenn der Tag leer ist (Sonntag?), kommt das Element vielleicht nicht.
                # Wir warten kurz dynamisch.
                try:
                    page.wait_for_selector("rect[data-event-event-value]", timeout=4000)
                    status = "✅ Daten"
                except:
                    status = "⚪ Leer/Läd nicht"

                # Ein bisschen extra Zeit für den Rest der Seite
                time.sleep(1)

                content = page.content()
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                
                print(f" -> Gespeichert ({status}, {len(content)/1024:.1f} KB)")

            except Exception as e:
                print(f" -> ❌ Fehler: {e}")

        browser.close()
    print("--- ✅ BULK DUMP FERTIG ---")

if __name__ == "__main__":
    run_bulk_dump()
