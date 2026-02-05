import sys
import time
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.config import URLS

def debug_log(msg):
    print(f"[DEBUG] {msg}")

def run_debug():
    # Credentials laden
    data_dir = resolve_data_dir()
    settings_path = data_dir / "settings.json"
    accs = load_accounts(settings_path)
    
    if not accs:
        debug_log("Keine Accounts in settings.json gefunden.")
        return

    email = accs[0].email
    password = accs[0].password
    debug_log(f"Teste Login für: {email}")

    with sync_playwright() as p:
        debug_log("Starte Browser (Headless)...")
        # Wir nutzen die gleichen Settings wie im Worker
        browser = p.chromium.launch(headless=True, args=["--start-maximized", "--window-size=1600,900"])
        context = browser.new_context(viewport={"width": 1600, "height": 900}, locale="de-CH")
        page = context.new_page()
        
        try:
            # 1. Starten
            debug_log(f"Navigiere zu {URLS['event_add']}...")
            page.goto(URLS['event_add'])
            page.wait_for_load_state("domcontentloaded")
            debug_log(f"-> URL: {page.url}")
            
            # 2. Standortwahl (falls nötig)
            if "/select" in page.url:
                debug_log("Standortwahl erkannt. Wähle 'vonRoll'...")
                try:
                    if page.locator("#navbarDropDownRight").is_visible():
                        page.click("#navbarDropDownRight")
                    elif page.locator(".navbar-toggler").is_visible():
                        page.click(".navbar-toggler")
                    
                    # Kurze Pause für Animation
                    time.sleep(0.5)
                    page.click("a[href*='/set/1']")
                    page.wait_for_load_state("networkidle")
                except Exception as e:
                    debug_log(f"Warnung bei Standortwahl: {e}")
                debug_log(f"-> URL nach Wahl: {page.url}")

            # 3. Login Trigger suchen
            if "login" not in page.url and "wayf" not in page.url and "eduid" not in page.url:
                if page.locator("#navbarUser").is_visible():
                    debug_log("Bereits eingeloggt (Unwahrscheinlich).")
                else:
                    debug_log("Suche Login-Trigger (Klicke auf Kalender-Zelle)...")
                    # Versuche Timeline Klick wie im Hauptcode
                    if page.locator(".timeline-cell-clickable").count() > 0:
                        page.locator(".timeline-cell-clickable").first.click()
                    else:
                        # Fallback Blindklick
                        debug_log("Keine Zellen -> Blindklick (800, 450)")
                        page.mouse.click(800, 450)
                    time.sleep(3)
                    debug_log(f"-> URL nach Trigger: {page.url}")

            # 4. Login Ausfüllen
            if page.locator("#username").is_visible() or "eduid" in page.url:
                debug_log("Login-Maske gefunden.")
                
                # Username
                if page.locator("#username").is_visible():
                    debug_log("Fülle Username...")
                    page.fill("#username", email)
                    page.keyboard.press("Enter")
                    time.sleep(2)
                
                # Passwort
                if page.locator("#password").is_visible():
                    debug_log("Fülle Passwort...")
                    page.fill("#password", password)
                    page.keyboard.press("Enter")
                    
                    debug_log("Login abgeschickt. Warte 10s auf Resultat...")
                    time.sleep(10) # Lange warten
                    
                    debug_log(f"-> FINAL URL: {page.url}")
                    
                    # ANALYSE
                    if "/event/add" in page.url and "login" not in page.url:
                        debug_log("✅ LOGIN SCHEINT ERFOLGREICH (Zurück auf Event Page).")
                        # Prüfen ob wir Räume sehen
                        opts = page.locator("#event_room option").all()
                        debug_log(f"Gefundene Raum-Optionen: {len(opts)}")
                    elif page.locator("#navbarUser").is_visible():
                        debug_log("✅ LOGIN ERFOLGREICH (#navbarUser sichtbar).")
                    else:
                        debug_log("❌ LOGIN FEHLGESCHLAGEN. Was sehen wir?")
                        debug_log("--- SEITEN-INHALT (Ausschnitt) ---")
                        # Wir geben Text aus, um Fehlermeldungen zu sehen (z.B. 'Passwort falsch', 'Consent', etc.)
                        text = page.locator("body").inner_text()
                        # Bereinigen und kürzen
                        clean_text = '\n'.join([line.strip() for line in text.splitlines() if line.strip()])
                        print(clean_text[:1000]) 
                        debug_log("----------------------------------")
                        
                        # Screenshot Pfad ausgeben (falls gemountet, hier aber nur Text-Debug möglich)
                        debug_log("Tipp: Suche im Text oben nach 'falsch', 'error', 'consent' oder 'bestätigen'.")

            else:
                debug_log("Keine Login-Maske gefunden und nicht eingeloggt.")
                print(page.locator("body").inner_text()[:500])

        except Exception as e:
            debug_log(f"CRITICAL EXCEPTION: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    run_debug()
