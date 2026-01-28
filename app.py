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

system_log("--- SYSTEM START (V4.1) ---")

# --- CONFIGURATION ---
try:
    st.set_page_config(
        page_title="Room Booker Pro", 
        layout="centered", 
        initial_sidebar_state="collapsed"
    )
except: pass

# --- SESSION STATE SETUP ---
if "room_cache" not in st.session_state: st.session_state.room_cache = []
if "cookies" not in st.session_state: st.session_state.cookies = None 

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

    def get_context(self, p):
        browser = p.chromium.launch(headless=True)
        if st.session_state.cookies:
            system_log("Using existing session cookies...")
            context = browser.new_context(locale="de-CH", storage_state=st.session_state.cookies)
        else:
            system_log("Creating new session...")
            context = browser.new_context(locale="de-CH")
        return browser, context

    def _handle_auth(self, page, account):
        if "login" in page.url or "wayf" in page.url or "eduid" in page.url:
            system_log("Authentication required.")
            try:
                page.wait_for_selector("input", timeout=5000)
                user_field = "input[name='j_username'], #username"
                if page.is_visible(user_field):
                    page.fill(user_field, account['email'])
                
                if page.is_visible("input[type='password']"):
                    page.fill("input[type='password']", account['password'])
                    page.click("button[name='_eventId_proceed']", force=True)
                else:
                    page.keyboard.press("Enter")
                    time.sleep(2)
                    if page.is_visible("input[type='password']"):
                        page.fill("input[type='password']", account['password'])
                        page.click("button[name='_eventId_proceed']", force=True)
                
                page.wait_for_url("**/event/**", timeout=45000)
                return True
            except Exception as e:
                system_log(f"Auth error: {e}")
        return True

    def _ensure_location_and_page(self, page):
        if "/select" in page.url:
            try:
                page.click("main a[href*='/set/1']", force=True) # vonRoll
                page.wait_for_url("**/event/**", timeout=10000)
            except: pass
        
        if "/event/add" not in page.url:
            page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=45000)
            page.wait_for_load_state("domcontentloaded")

    def extract_rooms_multi_method(self, page, ui_log):
        """5 Methods to extract room data."""
        methods = [
            ("JS Selector #event_room", "() => Object.fromEntries(Array.from(document.querySelector('#event_room')?.options || []).filter(o => o.value).map(o => [o.innerText.strip(), o.value]))"),
            ("JS Generic Select", "() => { const s = Array.from(document.querySelectorAll('select')).find(x => x.options.length > 5); return s ? Object.fromEntries(Array.from(s.options).filter(o => o.value).map(o => [o.innerText.strip(), o.value])) : {}; }"),
            ("Playwright Locator", None),
            ("DOM Attribute Scan", "() => { const r = {}; document.querySelectorAll('option').forEach(o => { if(o.value && o.value.length < 5) r[o.innerText.trim()] = o.value; }); return r; }"),
            ("Hardcoded Database", None)
        ]

        for i, (name, script) in enumerate(methods, 1):
            try:
                res = {}
                if script:
                    res = page.evaluate(script)
                elif name == "Playwright Locator":
                    opts = page.locator("#event_room option").all()
                    for o in opts:
                        t, v = o.inner_text(), o.get_attribute("value")
                        if v: res[t.strip()] = v
                elif name == "Hardcoded Database":
                    res = {"vonRoll: Gruppenraum 001": "1", "vonRoll: Gruppenraum 002": "2", "vonRoll: Lounge": "11"}
                
                if res and len(res) > 2:
                    self.log(f"Method {i} ({name}) SUCCESS. Found {len(res)} rooms.", ui_log)
                    return res
                else:
                    self.log(f"Method {i} ({name}) failed or empty.", ui_log)
            except Exception as e:
                self.log(f"Method {i} ({name}) error: {str(e)[:50]}", ui_log)
        
        return {}

    def run_scan(self, account, ui_log):
        with sync_playwright() as p:
            browser, context = self.get_context(p)
            try:
                page = context.new_page()
                page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=45000)
                self._handle_auth(page, account)
                self._ensure_location_and_page(page)
                
                rooms = self.extract_rooms_multi_method(page, ui_log)
                if rooms:
                    st.session_state.cookies = context.storage_state()
                    return rooms
            except Exception as e:
                self.log(f"Process error: {e}", ui_log)
            finally:
                browser.close()
        return {}

    def run_booking(self, date_str, start, end, targets, accounts, is_sim, ui_log):
        # Time Splitting
        tasks = []
        fmt = "%H:%M"
        t_curr = datetime.datetime.strptime(start, fmt)
        t_end = datetime.datetime.strptime(end, fmt)
        while t_curr < t_end:
            t_next = t_curr + datetime.timedelta(hours=4)
            if t_next > t_end: t_next = t_end
            tasks.append({"start": t_curr.strftime(fmt), "end": t_next.strftime(fmt)})
            t_curr = t_next

        with sync_playwright() as p:
            browser, context = self.get_context(p)
            for i, task in enumerate(tasks):
                acc = accounts[i % len(accounts)]
                self.log(f"Block {i+1}: {task['start']} - {task['end']}", ui_log)
                try:
                    page = context.new_page()
                    page.goto("https://raumreservation.ub.unibe.ch/event/add", timeout=45000)
                    self._handle_auth(page, acc)
                    self._ensure_location_and_page(page)

                    room_map = self.extract_rooms_multi_method(page, None)
                    success = False
                    for r_name in targets:
                        if r_name in room_map:
                            rid = room_map[r_name]
                            self.log(f"Trying {r_name}...", ui_log)
                            page.goto("https://raumreservation.ub.unibe.ch/event/add")
                            page.select_option("#event_room", value=rid)
                            page.fill("#event_startDate", f"{date_str} {task['start']}")
                            page.keyboard.press("Enter")
                            
                            dur = int((datetime.datetime.strptime(task['end'], fmt) - datetime.datetime.strptime(task['start'], fmt)).total_seconds() / 60)
                            page.evaluate(f"document.getElementById('event_duration').value = '{dur}'; document.getElementById('event_duration').dispatchEvent(new Event('change', {{bubbles: true}}));")
                            page.fill("#event_title", "Study")
                            
                            if is_sim:
                                self.log("Simulation success.", ui_log)
                                success = True; break
                            else:
                                page.click("#event_submit")
                                try:
                                    page.wait_for_url("**/event**", timeout=5000)
                                    if "/add" not in page.url:
                                        self.log(f"Success: {r_name}", ui_log); success = True; break
                                except: pass
                    
                    if not success: self.log("No rooms available in this block.", ui_log)
                    st.session_state.cookies = context.storage_state()
                    page.close()
                except Exception as e:
                    self.log(f"Block error: {e}", ui_log)
            browser.close()

# --- UI ---
accounts = get_accounts()
st.title("Room Booker Pro")

if not accounts:
    st.error("No accounts found in Environment Variables.")
    st.stop()

with st.expander("Rooms Database", expanded=not st.session_state.room_cache):
    if st.button("Refresh Room List", use_container_width=True):
        with st.status("Scanning...", expanded=True) as status:
            log_box = st.empty()
            res = RoomBot().run_scan(accounts[0], log_box)
            if res:
                st.session_state.room_cache = list(res.keys())
                status.update(label="Scan Complete", state="complete")
            else: status.update(label="Scan Failed", state="error")

room_options = st.session_state.room_cache if st.session_state.room_cache else ["Scan required"]

with st.form("main_form"):
    st.subheader("Reservation")
    c1, c2 = st.columns([1, 2])
    with c1: date_val = st.date_input("Date", datetime.datetime.now() + datetime.timedelta(days=1))
    with c2:
        cc1, cc2 = st.columns(2)
        with cc1: start_val = st.text_input("Start", "08:00")
        with cc2: end_val = st.text_input("End", "18:00")
    
    target_rooms = st.multiselect("Preferred Rooms", room_options)
    sim_mode = st.toggle("Simulation Mode", value=True)
    
    if st.form_submit_button("Start Process", type="primary", use_container_width=True):
        if not target_rooms or "Scan" in room_options[0]:
            st.error("Please update room list and select rooms.")
        else:
            with st.status("Executing...", expanded=True) as status:
                log_box = st.empty()
                RoomBot().run_booking(date_val.strftime("%d.%m.%Y"), start_val, end_val, target_rooms, accounts, sim_mode, log_box)
                status.update(label="Process Finished", state="complete")
