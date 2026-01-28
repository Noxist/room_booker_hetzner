import streamlit as st
import os
import time
import datetime
import sys
from playwright.sync_api import sync_playwright

# --- SYSTEM LOGGING (Sichtbar in der Shipper Konsole) ---
def system_log(msg):
    """Schreibt Logs direkt in die Server-Konsole."""
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
    system_log(f"CRITICAL ERROR loading config: {e}")

# --- HELFER FUNKTIONEN ---
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
        system_log(msg) # Immer in die Konsole
        if ui_container:
            ui_container.text(f">> {msg}")

    def scan_rooms(self, account):
        system_log("Starte Room Scan...")
        rooms = {}
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                system_log(f"Navigiere zur Uni Seite mit {account['email'][:3]}***")
                page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=30000)
                
                # Login Logik
                if "login" in page.url or "wayf" in page.url:
                    system_log("Login erforderlich...")
                    if page.is_visible("input[name='j_username']"):
                        page.fill("input[name='j_username']", account['email'])
                    elif page.is_visible("#username"):
                        page.fill("#username", account['email'])
                    
                    if page.is_visible("input[type='password']"):
                        page.fill("input[type='password']", account['password'])
                        page.click("button[name='_eventId_proceed']", force=True)
                    else:
                        page.keyboard.press("Enter")
                        time.sleep(1)
                        if page.is_visible("input[type='password']"):
                            page.fill("input[type='password']", account['password'])
                            page.click("button[name='_eventId_proceed']", force=True)
                    
                    page.wait_for_url("**/event/**", timeout=30000)
                    system_log("Login erfolgreich.")

                # Standortwahl
                if "/select" in page.url:
                    system_log("Wähle Standort...")
                    try:
                        page.click("main a[href*='/set/1']")
                        page.wait_for_url("**/event/**")
                    except: pass

                # Extraktion
                system_log("Extrahiere Raumdaten...")
                page.wait_for_load_state("domcontentloaded")
                
                rooms = page.evaluate("""() => {
                    const s = document.querySelector('#event_room');
                    if (!s) return {};
                    const r = {};
                    for (let o of s.options) { 
                        if(o.value && o.innerText) r[o.innerText.trim()] = o.value; 
                    }
                    return r;
                }""")
                system_log(f"Scan fertig. {len(rooms)} Räume gefunden.")
                browser.close()
                return rooms
                
            except Exception as e:
                system_log(f"SCAN FEHLER: {e}")
                return {}

    def execute_booking(self, date_str, start, end, target_rooms, accounts, is_sim, ui_log):
        system_log(f"Starte Buchungstask für {date_str}")
        
        # Zeitblöcke berechnen
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
                self.log(f"Block {i+1} ({task['start']}-{task['end']}) mit {acc['email']}", ui_log)
                
                context = browser.new_context(locale="de-CH")
                page = context.new_page()

                try:
                    page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=30000)
                    
                    # Login Check
                    if "login" in page.url or "wayf" in page.url:
                        try:
                            page.wait_for_selector("input", timeout=5000)
                            if page.is_visible("input[name='j_username']"):
                                page.fill("input[name='j_username']", acc['email'])
                            elif page.is_visible("#username"):
                                page.fill("#username", acc['email'])
                            
                            # PW
                            if page.is_visible("input[type='password']"):
                                page.fill("input[type='password']", acc['password'])
                                page.click("button[name='_eventId_proceed']", force=True)
                            else:
                                page.keyboard.press("Enter")
                                time.sleep(1)
                                if page.is_visible("input[type='password']"):
                                    page.fill("input[type='password']", acc['password'])
                                    page.click("button[name='_eventId_proceed']", force=True)
                            
                            page.wait_for_url("**/event/**", timeout=20000)
                        except:
                            self.log("Login fehlgeschlagen.", ui_log)
                            continue

                    # Standortwahl (Hier war der Syntaxfehler)
                    if "/select" in page.url:
                        try:
                            page.click("main a[href*='/set/1']")
                            page.wait_for_url("**/event/**")
                        except:
                            pass

                    # Buchungsschleife
                    booked = False
                    
                    # Mapping laden
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
                            self.log(f"Versuche {room_name}...", ui_log)
                            
                            # Reset
                            page.goto("https://raumreservation.ub.unibe.ch/event/add")
                            
                            # Ausfüllen
                            page.select_option("#event_room", value=rid)
                            page.fill("#event_startDate", f"{date_str} {task['start']}")
                            page.keyboard.press("Enter")
                            
                            # Dauer
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
                                    page.wait_for_url("**/event**", timeout=5000)
                                    if "/add" not in page.url:
                                        self.log(f"Erfolg: {room_name}", ui_log)
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
st.title("Room Booker Mobile")
accounts = get_accounts()

if not accounts:
    st.error("Prüfe Shipper Logs! Keine Accounts gefunden.")
    with st.expander("Manueller Login"):
        m_u = st.text_input("Email")
        m_p = st.text_input("Password", type="password")
        if m_u and m_p: accounts = [{"email":m_u, "password":m_p}]

# Raum Management
if "room_cache" not in st.session_state:
    st.session_state.room_cache = []

if st.button("Update Room List"):
    if accounts:
        with st.spinner("Scanne..."):
            s = RoomScraper()
            res = s.scan_rooms(accounts[0])
            if res:
                st.session_state.room_cache = list(res.keys())
                st.success(f"{len(res)} Räume gefunden")
            else:
                st.error("Scan fehlgeschlagen. Siehe Logs.")

rooms_list = st.session_state.room_cache if st.session_state.room_cache else ["Bitte erst scannen!"]

with st.form("book"):
    d = st.date_input("Datum")
    c1,c2 = st.columns(2)
    with c1: s = st.text_input("Start", "08:00")
    with c2: e = st.text_input("Ende", "18:00")
    
    tgt = st.multiselect("Räume", rooms_list)
    sim = st.checkbox("Simulation", True)
    
    if st.form_submit_button("Buchen", type="primary"):
        if accounts and tgt:
            log_box = st.empty()
            scraper = RoomScraper()
            scraper.execute_booking(d.strftime("%d.%m.%Y"), s, e, tgt, accounts, sim, log_box)
        else:
            st.error("Fehlende Accounts oder Räume.")
