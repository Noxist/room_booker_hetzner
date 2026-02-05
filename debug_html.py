import time
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.config import URLS

def run_html_dump(target_date_str):
    print(f"--- 🕵️ HTML DUMP FÜR {target_date_str} ---")
    data_dir = resolve_data_dir()
    accs = load_accounts(data_dir / "settings.json")
    if not accs: 
        print("❌ Keine Accounts.")
        return

    # Session wiederverwenden falls möglich
    session_files = list(data_dir.glob("session_*.json"))
    session_path = session_files[0] if session_files else None

    with sync_playwright() as p:
        print("Starte Browser...")
        browser = p.chromium.launch(headless=True)
        if session_path:
             context = browser.new_context(storage_state=str(session_path))
        else:
             context = browser.new_context()
        
        page = context.new_page()

        try:
            # Datum URL
            d_parts = target_date_str.split(".")
            iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
            target_url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            
            print(f"Navigiere zu: {target_url}")
            page.goto(target_url)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            # Standort Fix
            if "/select" in page.url or "Standort" in page.title():
                print("ℹ️ Setze Standort auf vonRoll...")
                page.goto("https://raumreservation.ub.unibe.ch/set/1")
                time.sleep(1)
                page.goto(target_url)
                time.sleep(2)

            # Login Check
            if "login" in page.url or "wayf" in page.url:
                print("⚠️ Login nötig...")
                if page.locator("#username").is_visible():
                    page.fill("#username", accs[0].email)
                    page.keyboard.press("Enter")
                    time.sleep(2)
                    page.fill("#password", accs[0].password)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("networkidle")
                    
                    new_session = data_dir / f"session_{accs[0].email.replace('@','_')}.json"
                    context.storage_state(path=str(new_session))
                    page.goto(target_url)
                    time.sleep(3)

            print("⏳ Warte 10 Sekunden auf vollständiges Rendering...")
            time.sleep(10)
            
            # HTML holen
            print("💾 Speichere HTML...")
            content = page.content()
            
            with open("full_dump.html", "w", encoding="utf-8") as f:
                f.write(content)
            
            print(f"✅ HTML gespeichert in 'full_dump.html' ({len(content)} Zeichen)")
            
            # Kleiner Check vorab: Suchen wir nach einem bekannten Raum?
            if "D-204" in content:
                print("👍 Raum 'D-204' im HTML gefunden!")
            else:
                print("⚠️ WARNUNG: Raum 'D-204' NICHT im HTML gefunden (Eventuell Iframe?).")

        except Exception as e:
            print(f"❌ Fehler: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    import sys
    import datetime
    target = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    if len(sys.argv) > 1:
        target = sys.argv[1]
    run_html_dump(target)
