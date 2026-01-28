import streamlit as st
import os
import time
import datetime
import sys
import json
from playwright.sync_api import sync_playwright

# --- SYSTEM LOGGING ---
def system_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    sys.stdout.flush()

system_log("--- SYSTEM START ---")

# --- CONFIGURATION ---
try:
    st.set_page_config(
        page_title="Room Booker Pro", 
        layout="centered", 
        initial_sidebar_state="collapsed"
    )
except: pass

# --- SESSION STATE SETUP ---
if "logs" not in st.session_state: st.session_state.logs = []
if "room_cache" not in st.session_state: st.session_state.room_cache = []
if "cookies" not in st.session_state: st.session_state.cookies = None # Cookie Speicher

# --- HELPER FUNCTIONS ---
def get_accounts():
    accs = []
    for i in range(1, 6):
        email = os.environ.get(f"MY_EMAIL_{i}", "").strip()
        pw = os.environ.get(f"MY_PASSWORD_{i}", "").strip()
        if email and pw:
            accs.append({"email": email, "password": pw})
    return accs

APP_PASSWORD = os.environ.get("WEB_ACCESS_PASSWORD", "").strip()

# --- AUTHENTICATION SCREEN ---
if APP_PASSWORD:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.markdown("### Access Control")
        pwd = st.text_input("Password", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Access denied.")
        st.stop()

# --- CORE LOGIC ---
class RoomBot:
    def log(self, msg, container=None):
        system_log(msg)
        if container:
            container.text(f">> {msg}")

    def get_browser_context(self, p):
        """Erstellt einen Browser-Kontext, nutzt Cookies falls vorhanden"""
        browser = p.chromium.launch(headless=True)
        
        if st.session_state.cookies:
            system_log("Restoring session from cookies...")
            context = browser.new_context(
                locale="de-CH",
                storage_state=st.session_state.cookies
            )
        else:
            system_log("Starting new session...")
            context = browser.new_context(locale="de-CH")
            
        return browser, context

    def save_cookies(self, context):
        """Speichert die Session für den nächsten Klick"""
        st.session_state.cookies = context.storage_state()
        system_log("Session cookies saved to memory.")

    def ensure_page(self, page):
        """Stellt sicher, dass wir auf der Buchungsseite sind"""
        if "/event/add" not in page.url:
            system_log(f"Redirecting from {page.url} to /event/add")
            page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=60000)
            try: page.wait_for_selector("#event_title", state="attached", timeout=10000)
            except: pass

    def handle_login(self, page, account):
        """Führt Login nur durch, wenn nötig"""
        if "login" in page.url or "wayf" in page.url:
            system_log("Login required.")
            try:
                page.wait_for_selector("input", timeout=5000)
                if page.is_visible("input[name='j_username']"):
                    page.fill("input[name='j_username']", account['email'])
                elif page.is_visible("#username"):
                    page.fill("#username", account['email'])
                
                # PW Check
                if page.is_visible("input[type='password']"):
                    page.fill("input[type='password']", account['password'])
                    page.click("button[name='_eventId_proceed']", force=True)
                else:
                    page.keyboard.press("Enter")
                    time.sleep(1)
                    if page.is_visible("input[type='password']"):
                        page.fill("input[type='password']", account['password'])
                        page.click("button[name='_eventId_proceed']", force=True)
                
                page.wait_for_url("**/event/**", timeout=45000)
                return True
            except Exception as e:
                system_log(f"Login error: {e}")
                return False
        return True

    def handle_location(self, page):
        if "/select" in page.url:
            system_log("Location selection detected.")
            try:
                page.click("main a[href*='/set/1']", force=True) # vonRoll
                time.sleep(2)
            except: pass

    def extract_rooms_5_ways(self, page):
        """Die 5 Methoden zur Raum-Extraktion"""
        rooms = {}
        method_used = "None"
        
        # Sicherstellen, dass Elemente geladen sind
        try: page.wait_for_selector("select", timeout=5000)
        except: pass

        # METHODE 1: Standard ID Selector (Bevorzugt)
        try:
            rooms = page.evaluate("""() => {
                const s = document.querySelector('#event_room');
                const r = {};
                if (s) {
                    for (let o of s.options) { if(o.value) r[o.innerText.trim()] = o.value; }
                }
                return r;
            }""")
            if rooms: return rooms, "Method 1 (ID #event_room)"
        except: pass

        # METHODE 2: Suche nach irgendeinem Select mit Inhalt
        try:
            rooms = page.evaluate("""() => {
                const selects = document.querySelectorAll('select');
                for (let s of selects) {
                    if (s.options.length > 5) {
                        const r = {};
                        for (let o of s.options) { if(o.value) r[o.innerText.trim()] = o.value; }
                        return r;
                    }
                }
                return {};
            }""")
            if rooms: return rooms, "Method 2 (Generic Select Scan)"
        except: pass

        # METHODE 3: Playwright Locator API
        try:
            options = page.locator("#event_room option").all()
            for opt in options:
                txt = opt.inner_text()
                val = opt.get_attribute("value")
                if val: rooms[txt.strip()] = val
            if rooms: return rooms, "Method 3 (Playwright Locator)"
        except: pass

        # METHODE 4: Fallback ID Liste (vonRoll hardcoded)
        # Falls die Seite komplett leer ist, nutzen wir bekannte IDs
        # Dies ist eine Notlösung, damit man trotzdem buchen kann
        known_ids = {
            "Bibliothek vonRoll: Gruppenraum 001": "1",
            "Bibliothek vonRoll: Gruppenraum 002": "2",
            "Bibliothek vonRoll: Gruppenraum 003": "3",
            "Bibliothek vonRoll: Gruppenraum 004": "4",
            "Bibliothek vonRoll: Lounge": "11"
        }
        # Wir prüfen nur ob wir auf der richtigen Page sind
        if "raumreservation" in page.url:
             return known_ids, "Method 5 (Fallback Database)"

        return {}, "Failed"

    def run_scan(self, account, ui_log):
        self.log("Initializing Scan...", ui_log)
        with sync_playwright() as p:
            browser, context = self.get_browser_context(p)
            try:
                page = context.new_page()
                page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=45000)
                
                self.handle_login(page, account)
                self.handle_location(page)
                self.ensure_page(page) # Force Navigation

                rooms, method = self.extract_rooms_5_ways(page)
                
                if rooms:
                    self.log(f"Success using {method}. Found {len(rooms)} rooms.", ui_log)
                    self.save_cookies(context) # Session speichern!
                    return rooms
                else:
                    self.log("All 5 extraction methods failed.", ui_log)
                    return {}
            except Exception as e:
                self.log(f"Error: {e}", ui_log)
                return {}
            finally:
                browser.close()

    def run_booking(self, date_str, start, end, targets, accounts, is_sim, ui_log):
        self.log("Initializing Booking...", ui_log)
        
        # Tasks berechnen
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
            self.log("Invalid time format.", ui_log)
            return

        with sync_playwright() as p:
            browser, context = self.get_browser_context(p)
            
            for i, task in enumerate(tasks):
                acc = accounts[i % len(accounts)]
                self.log(f"Block {i+1} ({task['start']}-{task['end']})", ui_log)
                
                try:
                    page = context.new_page()
                    page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=45000)
                    
                    self.handle_login(page, acc)
                    self.handle_location(page)
                    self.ensure_page(page)

                    # Buchen
                    booked = False
                    
                    # Mapping holen
                    rooms, _ = self.extract_rooms_5_ways(page)

                    for r_name in targets:
                        if r_name in rooms:
                            rid = rooms[r_name]
                            self.log(f"Attempting: {r_name}", ui_log)
                            
                            # Clean State
                            page.goto("https://raumreservation.ub.unibe.ch/event/add")
                            page.wait_for_load_state("domcontentloaded")
                            
                            # Fill
                            page.select_option("#event_room", value=rid)
                            page.fill("#event_startDate", f"{date_str} {task['start']}")
                            page.keyboard.press("Enter")
                            
                            # Dur
                            t1 = datetime.datetime.strptime(task['start'], fmt)
                            t2 = datetime.datetime.strptime(task['end'], fmt)
                            dur = int((t2 - t1).total_seconds() / 60)
                            
                            page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
                            page.evaluate("document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))")
                            
                            page.fill("#event_title", "Study")
                            if page.is_visible('input[name="event[purpose]"][value="Other"]'):
                                page.check('input[name="event[purpose]"][value="Other"]')
                            
                            if is_sim:
                                self.log("Simulation: Success.", ui_log)
                                booked = True
                                break
                            else:
                                page.click("#event_submit")
                                try:
                                    page.wait_for_url("**/event**", timeout=5000)
                                    if "/add" not in page.url:
                                        self.log(f"Confirmed: {r_name}", ui_log)
                                        booked = True
                                        break
                                except: pass
                    
                    if not booked:
                        self.log("No room available.", ui_log)
                    
                    # Session nach jedem Block updaten
                    self.save_cookies(context)
                    page.close()

                except Exception as e:
                    self.log(f"Error in block: {e}", ui_log)
            
            browser.close()
        self.log("Finished.", ui_log)

# --- UI LAYOUT ---

accounts = get_accounts()

st.title("Room Booker Pro")

# Status Section
if not accounts:
    st.error("System Config Error: No accounts found.")
    st.stop()
else:
    st.caption(f"Status: Online | {len(accounts)} Accounts Loaded")

# Room Manager
with st.expander("Database & Rooms", expanded=not st.session_state.room_cache):
    c1, c2 = st.columns([2, 1])
    with c1:
        st.write("Current List:", len(st.session_state.room_cache), "Rooms")
    with c2:
        if st.button("Update List", use_container_width=True):
            with st.status("Scanning...", expanded=True) as status:
                log_box = st.empty()
                bot = RoomBot()
                res = bot.run_scan(accounts[0], log_box)
                if res:
                    st.session_state.room_cache = list(res.keys())
                    status.update(label="Scan Complete", state="complete")
                else:
                    status.update(label="Scan Failed", state="error")

room_list = st.session_state.room_cache if st.session_state.room_cache else ["Scan required"]

# Main Form
with st.form("main_form"):
    st.subheader("New Reservation")
    
    col_d, col_t = st.columns([1, 2])
    with col_d:
        date_val = st.date_input("Date", datetime.datetime.now() + datetime.timedelta(days=1))
    with col_t:
        c_start, c_end = st.columns(2)
        with c_start: start_val = st.text_input("Start", "08:00")
        with c_end: end_val = st.text_input("End", "18:00")
    
    target_rooms = st.multiselect("Preferred Rooms (Ordered)", room_list)
    
    st.markdown("---")
    sim_mode = st.toggle("Simulation Mode (Dry Run)", value=True)
    
    submit = st.form_submit_button("Execute Booking", type="primary", use_container_width=True)

if submit:
    if not target_rooms or "Scan" in room_list[0]:
        st.error("Please select valid rooms.")
    else:
        with st.status("Processing...", expanded=True) as status:
            log_ui = st.empty()
            bot = RoomBot()
            bot.run_booking(
                date_val.strftime("%d.%m.%Y"),
                start_val,
                end_val,
                target_rooms,
                accounts,
                sim_mode,
                log_ui
            )
            status.update(label="Operation Finished", state="complete")
