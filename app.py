import streamlit as st
import os
import time
import datetime
import sys
from playwright.sync_api import sync_playwright

# --- SYSTEM LOGGING ---
def system_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    sys.stdout.flush()

system_log("--- APP STARTUP INITIATED ---")

# --- KONFIGURATION ---
try:
    st.set_page_config(
        page_title="Room Booker", 
        layout="centered", 
        initial_sidebar_state="collapsed"
    )
    system_log("Streamlit Config loaded.")
except Exception as e:
    pass

# --- HELPER FUNCTIONS ---
def get_accounts():
    accs = []
    system_log("Lade Accounts aus Environment Variables...")
    for i in range(1, 6):
        key_email = f"MY_EMAIL_{i}"
        key_pw = f"MY_PASSWORD_{i}"
        
        email = os.environ.get(key_email, "").strip()
        pw = os.environ.get(key_pw, "").strip()
        
        if email and pw:
            accs.append({"email": email, "password": pw})
            system_log(f"Account {i} gefunden.")
    
    if not accs:
        system_log("WARNUNG: Keine Accounts in Env Vars gefunden.")
    return accs

APP_PASSWORD = os.environ.get("WEB_ACCESS_PASSWORD", "").strip()

# --- AUTHENTICATION ---
if APP_PASSWORD:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.header("Login")
        pwd = st.text_input("Password", type="password")
        if st.button("Login"):
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Falsches Passwort.")
        st.stop()

# --- BACKEND LOGIK ---
class RoomScraper:
    def log(self, msg, ui_container=None):
        system_log(msg)
        if ui_container:
            ui_container.text(f">> {msg}")

    def _handle_login(self, page, account):
        """Zentralisierte Login-Logik"""
        if "login" in page.url or "wayf" in page.url:
            system_log("Login Maske erkannt...")
            try:
                page.wait_for_selector("input", timeout=5000)
                
                # Email
                if page.is_visible("input[name='j_username']"):
                    page.fill("input[name='j_username']", account['email'])
                elif page.is_visible("#username"):
                    page.fill("#username", account['email'])
                
                # Passwort (direkt oder nach Enter)
                if page.is_visible("input[type='password']"):
                    page.fill("input[type='password']", account['password'])
                    page.click("button[name='_eventId_proceed']", force=True)
                else:
                    page.keyboard.press("Enter")
                    time.sleep(1)
                    if page.is_visible("input[type='password']"):
                        page.fill("input[type='password']", account['password'])
                        page.click("button[name='_eventId_proceed']", force=True)
                
                # Warten auf Redirect
                page.wait_for_url("**/event/**", timeout=45000)
                system_log("Login erfolgreich abgeschlossen.")
                return True
            except Exception as e:
                system_log(f"Login Fehler: {e}")
                return False
        return True

    def scan_rooms(self, account):
        system_log("Starte Room Scan (Optimiert)...")
        rooms = {}
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(locale="de-CH")
                page = context.new_page()
                
                system_log(f"Navigiere zur Uni Seite...")
                page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=45000)
                
                # 1. Login
                self._handle_login(page, account)

                # 2. Standortwahl (Aggressiv)
                if "/select" in page.url:
                    system_log("Wähle Standort 'vonRoll'...")
                    try:
                        # Wir warten kurz, ob der Link klickbar ist
                        page.wait_for_selector("main a[href*='/set/1']", timeout=5000)
                        page.click("main a[href*='/set/1']", force=True)
                        # Explizit warten, dass wir die Seite verlassen
                        page.wait_for_url("**/event/**", timeout=30000)
                    except Exception as e:
                        system_log(f"Warnung bei Standortwahl: {e}")

                # 3. Warten auf Daten (Smart Wait)
                system_log("Warte auf Raum-Liste...")
                try:
                    # Wir warten explizit, bis mindestens eine <option> im Select ist
                    page.wait_for_selector("#event_room option", timeout=15000)
                except:
                    system_log("Timeout: Liste scheint leer zu bleiben.")

                # 4. Extraktion
                rooms = page.evaluate("""() => {
                    const s = document.querySelector('#event_room');
                    if (!s) return {};
                    const r = {};
                    for (let o of s.options) { 
                        if(o.value && o.innerText && o.value.trim() !== "") {
                            r[o.innerText.trim()] = o.value; 
                        }
                    }
                    return r;
                }""")
                
                system_log(f"Scan fertig. {len(rooms)} Räume gefunden.")
                browser.close()
                return rooms
                
            except Exception as e:
                system_log(f"CRITICAL SCAN ERROR: {e}")
                return {}

    def execute_booking(self, date_str, start, end, target_rooms, accounts, is_sim, ui_log):
        system_log(f"Starte Buchungstask für {date_str}")
        
        tasks = []
        fmt = "%H:%M"
        try:
            t_curr = datetime.datetime.strptime(start, fmt)
            t_end = datetime.datetime.strptime(end, fmt)
            while t_curr < t_end:
                t_next = t_curr + datetime.timedelta(hours=4)
                if t_next > t_end: t_next = t_end
                tasks.append({"start": t_curr.strftime(fmt), "end": t_next.strftime(fmt)})
                t_curr = t_next
        except:
            self.log("Fehler beim Zeitformat.", ui_log)
            return

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            for i, task in enumerate(tasks):
                acc = accounts[i % len(accounts)]
                self.log(f"Block {i+1} ({task['start']}-{task['end']})", ui_log)
                
                context = browser.new_context(locale="de-CH")
                page = context.new_page()

                try:
                    page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=45000)
                    
                    self._handle_login(page, acc)

                    if "/select" in page.url:
                        try:
                            page.click("main a[href*='/set/1']", force=True)
                            page.wait_for_url("**/event/**", timeout=10000)
                        except: pass

                    # Buchungsversuch
                    booked = False
                    
                    # Warte kurz auf DOM
                    try: page.wait_for_selector("#event_room option", timeout=5000)
                    except: pass
                    
                    # Map erstellen
                    room_map = page.evaluate("""() => {
                        const s = document.querySelector('#event_room');
                        if (!s) return {};
                        const r = {};
                        for (let o of s.options) { if(o.value) r[o.innerText.trim()] = o.value; }
                        return r;
                    }""")

                    for room_name in target_rooms:
                        if room_name in room_map:
                            rid = room_map[room_name]
                            self.log(f"Versuche: {room_name}", ui_log)
                            
                            # Formular Refill (Sicherer)
                            page.goto("https://raumreservation.ub.unibe.ch/event/add")
                            page.wait_for_load_state("domcontentloaded")
                            
                            page.select_option("#event_room", value=rid)
                            page.fill("#event_startDate", f"{date_str} {task['start']}")
                            page.keyboard.press("Enter")
                            
                            # Dauer berechnen
                            t1 = datetime.datetime.strptime(task['start'], fmt)
                            t2 = datetime.datetime.strptime(task['end'], fmt)
                            dur = int((t2 - t1).total_seconds() / 60)
                            
                            page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
                            page.evaluate("document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))")
                            
                            page.fill("#event_title", "Study")
                            if page.is_visible('input[name="event[purpose]"][value="Other"]'):
                                page.check('input[name="event[purpose]"][value="Other"]')
                            
                            if is_sim:
                                self.log("Simulation OK.", ui_log)
                                booked = True
                                break
                            else:
                                page.click("#event_submit")
                                try:
                                    # Erfolgscheck: URL Wechsel oder Success Message
                                    page.wait_for_url("**/event**", timeout=5000)
                                    if "/add" not in page.url:
                                        self.log(f"ERFOLG: {room_name}", ui_log)
                                        booked = True
                                        break
                                except: pass
                        
                    if not booked:
                        self.log("Kein Raum gefunden.", ui_log)

                except Exception as e:
                    self.log(f"Fehler: {e}", ui_log)
                finally:
                    context.close()
            
            browser.close()
        self.log("Fertig.", ui_log)

# --- UI ---
st.title("Mobile Room Booker")
accounts = get_accounts()

if not accounts:
    st.error("Prüfe Logs! Keine Accounts gefunden.")
    with st.expander("Notfall Login"):
        m_u = st.text_input("Email")
        m_p = st.text_input("Password", type="password")
        if m_u and m_p: accounts = [{"email":m_u, "password":m_p}]

# Raum Management
if "room_cache" not in st.session_state:
    st.session_state.room_cache = []

if st.button("Update Room List", use_container_width=True):
    if accounts:
        with st.spinner("Scanne... (Kann bis zu 60s dauern)"):
            s = RoomScraper()
            res = s.scan_rooms(accounts[0])
            if res:
                st.session_state.room_cache = list(res.keys())
                st.success(f"{len(res)} Räume gefunden!")
            else:
                st.error("Scan fehlgeschlagen - 0 Räume. Siehe Logs.")

rooms_list = st.session_state.room_cache if st.session_state.room_cache else ["Bitte erst scannen!"]

with st.form("book"):
    st.subheader("Buchung")
    d = st.date_input("Datum", datetime.datetime.now() + datetime.timedelta(days=1))
    c1,c2 = st.columns(2)
    with c1: s = st.text_input("Start", "08:00")
    with c2: e = st.text_input("Ende", "18:00")
    
    tgt = st.multiselect("Räume", rooms_list)
    sim = st.checkbox("Simulation (Nur Test)", value=True)
    
    if st.form_submit_button("Buchen Starten", type="primary", use_container_width=True):
        if accounts and tgt and "Bitte" not in rooms_list[0]:
            log_box = st.empty()
            scraper = RoomScraper()
            scraper.execute_booking(d.strftime("%d.%m.%Y"), s, e, tgt, accounts, sim, log_box)
        else:
            st.error("Bitte Räume scannen und auswählen.")
