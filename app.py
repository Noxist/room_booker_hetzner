import streamlit as st
import os
import time
import datetime
from playwright.sync_api import sync_playwright

# --- KONFIGURATION ---
st.set_page_config(page_title="Room Booker Cloud", page_icon="⚡")

# --- HILFSFUNKTIONEN ---
def get_accounts_debug():
    """
    Versucht Accounts zu laden und gibt Debug-Infos zurück,
    damit du am Handy siehst, was los ist.
    """
    accs = []
    logs = []
    
    # Wir suchen nach MY_EMAIL_1 bis MY_EMAIL_5
    for i in range(1, 6):
        key_email = f"MY_EMAIL_{i}"
        key_pw = f"MY_PASSWORD_{i}"
        
        # .strip() entfernt versehentliche Leerzeichen vom Handy-Tippen
        email = os.environ.get(key_email, "").strip()
        pw = os.environ.get(key_pw, "").strip()
        
        if email and pw:
            accs.append({"email": email, "password": pw})
            # Zeige nur die ersten 3 Zeichen der Mail zur Sicherheit
            safe_mail = email[:3] + "***" if len(email) > 3 else "***"
            logs.append(f"✅ {key_email} gefunden ({safe_mail})")
        else:
            # Nur loggen wenn einer der beiden Teile da ist, um Verwirrung zu vermeiden
            if email or pw:
                logs.append(f"⚠️ {key_email} unvollständig (PW fehlt?)")
            # else: logs.append(f"Start: Suche nach {key_email}...")

    return accs, logs

# Passwortschutz für die Webseite selbst
APP_PASSWORD = os.environ.get("WEB_ACCESS_PASSWORD", "").strip()

# --- UI START ---

# 1. Web-Zugriffsschutz
if APP_PASSWORD:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 Login")
        pwd = st.text_input("Web-Passwort", type="password")
        if st.button("Entsperren"):
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Falsch.")
        st.stop()

# 2. Account Check
accounts, debug_logs = get_accounts_debug()

st.title("⚡ Uni Bern Booker")

# Debug Expander (Damit du siehst, was Shipper macht)
with st.expander("🔍 System Status / Debug Logs", expanded=not accounts):
    st.write("Suche nach Umgebungsvariablen:")
    if not debug_logs:
        st.warning("Keine Variablen wie 'MY_EMAIL_1' gefunden.")
    for log in debug_logs:
        st.text(log)
    
    st.info("Hinweis: Wenn hier nichts steht, prüfen Sie im Shipper Dashboard unter 'Variables', ob 'MY_EMAIL_1' exakt so geschrieben ist.")

# Fallback: Manuelle Eingabe, falls Env Vars streiken
if not accounts:
    st.error("⚠️ Keine Accounts geladen. Bitte manuell eingeben:")
    man_email = st.text_input("Notfall-Email")
    man_pw = st.text_input("Notfall-Passwort", type="password")
    if man_email and man_pw:
        accounts = [{"email": man_email, "password": man_pw}]
        st.success("Manueller Account bereit!")

# Wenn immer noch keine Accounts da sind -> Stopp
if not accounts:
    st.stop()

st.success(f"{len(accounts)} Account(s) bereit zum Buchen!")

# --- BUCHUNGSLOGIK ---

class CloudBooker:
    def __init__(self):
        self.log_area = st.empty()
        self.logs = []

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.logs.append(entry)
        self.log_area.code("\n".join(self.logs))
        print(entry)

    def run(self, date_str, start_str, end_str, rooms, account_list, is_sim):
        self.log(f"🚀 Starte Prozess für {date_str} ({start_str}-{end_str})")
        
        # Zeitblöcke berechnen
        try:
            tasks = []
            fmt = "%H:%M"
            t_curr = datetime.datetime.strptime(start_str, fmt)
            t_end = datetime.datetime.strptime(end_str, fmt)
            
            while t_curr < t_end:
                t_next = t_curr + datetime.timedelta(hours=4)
                if t_next > t_end: t_next = t_end
                tasks.append({"start": t_curr.strftime(fmt), "end": t_next.strftime(fmt)})
                t_curr = t_next
        except Exception as e:
            self.log(f"Fehler beim Zeitformat: {e}")
            return

        with sync_playwright() as p:
            # Headless = True für Server!
            browser = p.chromium.launch(headless=True)
            
            for i, task in enumerate(tasks):
                # Round Robin Account Auswahl
                acc = account_list[i % len(account_list)]
                self.log(f"\n--- Block {i+1}: {task['start']} bis {task['end']} ---")
                self.log(f"Nutze Account: {acc['email'][:4]}***")
                
                context = browser.new_context(locale="de-CH")
                page = context.new_page()

                try:
                    # 1. Login
                    page.goto("https://raumreservation.ub.unibe.ch/event/add")
                    
                    if "login" in page.url or "wayf" in page.url or "eduid" in page.url:
                        self.log("Login nötig...")
                        # Versuch Email
                        try:
                            page.wait_for_selector("input", timeout=3000)
                            if page.is_visible("input[name='j_username']"):
                                page.fill("input[name='j_username']", acc['email'])
                            elif page.is_visible("#username"):
                                page.fill("#username", acc['email'])
                            
                            # PW Check
                            if page.is_visible("input[type='password']"):
                                page.fill("input[type='password']", acc['password'])
                                page.click("button[name='_eventId_proceed']", force=True)
                            else:
                                page.keyboard.press("Enter")
                                time.sleep(1)
                                if page.is_visible("input[type='password']"):
                                    page.fill("input[type='password']", acc['password'])
                                    page.click("button[name='_eventId_proceed']", force=True)
                            
                            page.wait_for_url("**/event/**", timeout=15000)
                            self.log("Login OK.")
                        except:
                            self.log("Login Timeout oder Fehler.")
                            continue # Nächster Block

                    # 2. Standort
                    if "/select" in page.url:
                        try:
                            page.click("main a[href*='/set/1']")
                            page.wait_for_url("**/event/**")
                        except: pass

                    # 3. Raum suchen
                    # Wir laden die Liste via JS
                    time.sleep(1)
                    js_rooms = page.evaluate("""() => {
                        const s = document.querySelector('#event_room');
                        if (!s) return {};
                        const r = {};
                        for (let o of s.options) { if(o.value) r[o.innerText.trim()] = o.value; }
                        return r;
                    }""")
                    
                    booked = False
                    for room_name in rooms:
                        if room_name in js_rooms:
                            rid = js_rooms[room_name]
                            self.log(f"Versuche '{room_name}'...")
                            
                            # Formular füllen
                            page.goto("https://raumreservation.ub.unibe.ch/event/add")
                            time.sleep(0.5)
                            
                            # Raum setzen
                            page.select_option("#event_room", value=rid)
                            
                            # Zeit
                            full_start = f"{date_str} {task['start']}"
                            page.fill("#event_startDate", full_start)
                            page.keyboard.press("Enter")
                            time.sleep(0.5)
                            
                            # Dauer
                            t1 = datetime.datetime.strptime(task['start'], fmt)
                            t2 = datetime.datetime.strptime(task['end'], fmt)
                            dur = int((t2 - t1).total_seconds() / 60)
                            
                            page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
                            page.evaluate("document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))")
                            
                            # Titel
                            page.fill("#event_title", "Lernen")
                            if page.is_visible('input[name="event[purpose]"][value="Other"]'):
                                page.check('input[name="event[purpose]"][value="Other"]')
                                
                            if is_sim:
                                self.log("(Simulation) Wäre gebucht.")
                                booked = True
                                break
                            else:
                                page.click("#event_submit")
                                try:
                                    page.wait_for_url("**/event**", timeout=5000)
                                    if "/add" not in page.url:
                                        self.log(f"✅ ERFOLG: {room_name}")
                                        booked = True
                                        break
                                except:
                                    self.log(f"❌ {room_name} fehlgeschlagen.")

                    if not booked:
                        self.log("⚠️ Kein Raum für diesen Block gefunden.")

                except Exception as e:
                    self.log(f"Fehler im Prozess: {e}")
                finally:
                    context.close()
            
            browser.close()
        self.log("🏁 Vorgang beendet.")


# --- GUI INPUTS ---
col1, col2 = st.columns(2)
with col1:
    d_input = st.date_input("Datum", datetime.datetime.now() + datetime.timedelta(days=1))
with col2:
    s_input = st.text_input("Start", "08:00")
    e_input = st.text_input("Ende", "18:00")

# Standard-Liste (Kannst du erweitern)
room_list = [
    "Bibliothek vonRoll: Gruppenraum 001", "Bibliothek vonRoll: Gruppenraum 002",
    "Bibliothek vonRoll: Gruppenraum 003", "Bibliothek vonRoll: Gruppenraum 004",
    "Bibliothek vonRoll: Gruppenraum 005", "Bibliothek vonRoll: Gruppenraum B01",
    "Bibliothek vonRoll: Lounge"
]
sel_rooms = st.multiselect("Räume", room_list, default=room_list[:2])

chk_sim = st.checkbox("Simulation (Test)", value=True)

if st.button("Starten", type="primary"):
    bot = CloudBooker()
    bot.run(d_input.strftime("%d.%m.%Y"), s_input, e_input, sel_rooms, accounts, chk_sim)
