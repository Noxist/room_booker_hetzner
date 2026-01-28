import streamlit as st
import os
import time
import datetime
import threading
from playwright.sync_api import sync_playwright

# --- KONFIGURATION ---
# Versuche Login-Daten aus den Shipper Environment Variables zu laden
ENV_EMAIL = os.environ.get("MY_EMAIL", "")
ENV_PASSWORD = os.environ.get("MY_PASSWORD", "")
APP_PASSWORD = os.environ.get("WEB_ACCESS_PASSWORD", "admin") # Schutz für die Webseite

st.set_page_config(page_title="Uni Bern Room Bot", page_icon="📚")

# --- SICHERHEITS-CHECK ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

def check_password():
    if st.session_state.password_input == APP_PASSWORD:
        st.session_state.authenticated = True
    else:
        st.error("Falsches Passwort")

if not st.session_state.authenticated:
    st.title("🔒 Login")
    st.text_input("Zugriffspasswort", type="password", key="password_input", on_change=check_password)
    st.stop() # Stoppt hier, wenn nicht eingeloggt

# --- LOGIK (Headless angepasst) ---

class CloudBooker:
    def __init__(self):
        self.log_placeholder = st.empty()
        self.logs = []

    def log(self, msg):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {msg}")
        # Update UI Log live
        self.log_placeholder.code("\n".join(self.logs))
        print(f"[{timestamp}] {msg}")

    def run_process(self, date_str, start_time, end_time, room_preference, email, password, simulation):
        self.log("🚀 Starte Prozess im Container...")
        
        with sync_playwright() as p:
            # WICHTIG: In Docker immer headless=True
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="de-CH"
            )
            page = context.new_page()

            try:
                # 1. Login & Navigation
                self.log("Navigiere zur Uni-Seite...")
                page.goto("https://raumreservation.ub.unibe.ch/event/add")
                
                # Auto-Login Logik (Kompakt)
                if "login" in page.url or "wayf" in page.url or "eduid" in page.url:
                    self.log("Login Maske erkannt. Logge ein...")
                    try:
                        # Warte auf Inputs
                        page.wait_for_selector("input", timeout=5000)
                        
                        # Email
                        if page.is_visible("input[name='j_username']"):
                            page.fill("input[name='j_username']", email)
                            time.sleep(0.5)
                        elif page.is_visible("#username"):
                            page.fill("#username", email)

                        # Passwort Check (Switch Edu ID ist oft 2-Step)
                        if page.is_visible("input[type='password']"):
                            page.fill("input[type='password']", password)
                            page.click("button[name='_eventId_proceed']", force=True)
                        else:
                            # Nur Email Feld da -> Enter und warten auf Passwort Feld
                            page.keyboard.press("Enter")
                            time.sleep(2)
                            if page.is_visible("input[type='password']"):
                                page.fill("input[type='password']", password)
                                page.click("button[name='_eventId_proceed']", force=True)
                        
                        self.log("Login gesendet. Warte auf Redirect...")
                        page.wait_for_url("**/event/add**", timeout=15000)
                        self.log("Login erfolgreich!")
                    except Exception as e:
                        self.log(f"Login Problem: {e}")
                        return

                # 2. Standortwahl (Falls nötig)
                if "/select" in page.url:
                    self.log("Wähle Standort vonRoll...")
                    try:
                        page.click("main a[href*='/set/1']") # vonRoll ID
                        page.goto("https://raumreservation.ub.unibe.ch/event/add")
                    except:
                        pass

                # 3. Räume Scannen (Live Scan statt JSON Datei)
                self.log("Scanne verfügbare Räume (Live)...")
                page.wait_for_load_state("domcontentloaded")
                time.sleep(1)
                
                # JS Injection zum Auslesen der Räume
                room_map = page.evaluate("""() => {
                    const sel = document.querySelector('#event_room');
                    if (!sel) return null;
                    const res = {};
                    for (let i = 0; i < sel.options.length; i++) {
                        const opt = sel.options[i];
                        if (opt.value && opt.value.trim() !== "") {
                            res[opt.innerText.trim()] = opt.value;
                        }
                    }
                    return res;
                }""")

                if not room_map:
                    self.log("Fehler: Konnte Raumliste nicht laden.")
                    return

                # 4. Buchungsschleife
                target_room_id = None
                target_room_name = None

                # Wir suchen nach dem bevorzugten Raum
                for r_name in room_preference:
                    if r_name in room_map:
                        target_room_id = room_map[r_name]
                        target_room_name = r_name
                        self.log(f"Versuche Favorit: {target_room_name}")
                        
                        # Versuch zu buchen
                        if self._try_book_room(page, target_room_id, date_str, start_time, end_time, simulation):
                            self.log(f"✅ ERFOLG! {target_room_name} gebucht.")
                            return # Fertig
                        else:
                            self.log(f"❌ {target_room_name} nicht verfügbar. Nächster...")
                    
                self.log("Keine der gewünschten Räume konnte gebucht werden.")

            except Exception as e:
                self.log(f"Kritischer Fehler: {e}")
                # Screenshot für Debugging im Browser anzeigen
                try:
                    scr = page.screenshot()
                    st.image(scr, caption="Fehler Screenshot")
                except: pass
            finally:
                browser.close()

    def _try_book_room(self, page, room_id, date, start, end, simulation):
        try:
            # Refresh Formular
            page.goto("https://raumreservation.ub.unibe.ch/event/add")
            time.sleep(1)

            # Raum setzen
            page.select_option("#event_room", value=room_id)
            
            # Zeit
            page.fill("#event_startDate", f"{date} {start}")
            page.keyboard.press("Enter")
            time.sleep(1)

            # Dauer berechnen
            fmt = "%H:%M"
            t1 = datetime.datetime.strptime(start, fmt)
            t2 = datetime.datetime.strptime(end, fmt)
            dur = int((t2 - t1).total_seconds() / 60)

            # Dauer setzen
            page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
            page.evaluate("document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))")
            
            # Titel
            page.fill("#event_title", "Lernen")
            if page.is_visible('input[name="event[purpose]"][value="Other"]'):
                page.check('input[name="event[purpose]"][value="Other"]')

            if simulation:
                self.log("(Simulation) Button wäre jetzt gedrückt worden.")
                return True
            else:
                page.click("#event_submit")
                # Erfolg prüfen (Redirect oder Success Message)
                try:
                    page.wait_for_url("**/event**", timeout=5000)
                    if "/add" not in page.url:
                        return True
                except: pass
                
            return False
        except Exception as e:
            self.log(f"Buchungsversuch Fehler: {e}")
            return False

# --- UI AUFBAU ---

st.title("📚 Uni Bern Room Booker (Cloud)")

# Sidebar für Einstellungen
with st.sidebar:
    st.header("Einstellungen")
    sim_mode = st.checkbox("Simulations-Modus", value=True)
    
    st.markdown("---")
    st.markdown("**Account Status:**")
    if ENV_EMAIL and ENV_PASSWORD:
        st.success("✅ Credentials aus Env geladen")
        active_email = ENV_EMAIL
        active_pw = ENV_PASSWORD
    else:
        st.warning("⚠️ Keine Env Vars gefunden")
        active_email = st.text_input("Email")
        active_pw = st.text_input("Passwort", type="password")

# Hauptbereich
col1, col2 = st.columns(2)
with col1:
    date_input = st.date_input("Datum", datetime.datetime.now() + datetime.timedelta(days=1))
    # Konvertiere zu DD.MM.YYYY string
    date_str = date_input.strftime("%d.%m.%Y")

with col2:
    start_t = st.text_input("Startzeit", "08:00")
    end_t = st.text_input("Endzeit", "12:00")

# Raumauswahl (Hardcoded Liste oder dynamisch ist schwer ohne vorherigen Scan, wir nehmen Standard-Liste)
# Du kannst diese Liste erweitern!
known_rooms = [
    "Bibliothek vonRoll: Gruppenraum 001",
    "Bibliothek vonRoll: Gruppenraum 002",
    "Bibliothek vonRoll: Gruppenraum 003",
    "Bibliothek vonRoll: Gruppenraum 004",
    "Bibliothek vonRoll: Gruppenraum 005",
    "Bibliothek vonRoll: Gruppenraum B01",
    "Bibliothek vonRoll: Gruppenraum B02",
    "Bibliothek vonRoll: Lounge"
]

selected_rooms = st.multiselect("Räume (Priorität von oben nach unten)", known_rooms, default=[known_rooms[0]])

if st.button("Start Buchung", type="primary"):
    if not active_email or not active_pw:
        st.error("Keine Login-Daten vorhanden!")
    else:
        bot = CloudBooker()
        # Threading damit UI nicht einfriert
        bot.run_process(date_str, start_t, end_t, selected_rooms, active_email, active_pw, sim_mode)
