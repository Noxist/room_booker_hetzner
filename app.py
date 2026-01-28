import streamlit as st
import os
import time
import datetime
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Room Booker", 
    layout="centered", 
    initial_sidebar_state="collapsed"
)

# --- HELPER FUNCTIONS ---
def get_accounts():
    """Reads accounts from environment variables."""
    accs = []
    logs = []
    
    for i in range(1, 6):
        key_email = f"MY_EMAIL_{i}"
        key_pw = f"MY_PASSWORD_{i}"
        
        email = os.environ.get(key_email, "").strip()
        pw = os.environ.get(key_pw, "").strip()
        
        if email and pw:
            accs.append({"email": email, "password": pw})
            logs.append(f"Account {i} loaded.")
        elif email or pw:
            logs.append(f"Account {i} incomplete.")

    return accs, logs

# Access protection
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
                st.error("Incorrect password.")
        st.stop()

# --- BACKEND LOGIC ---

class RoomScraper:
    """Handles fetching the room list and booking."""
    
    def log(self, msg):
        # Writes to the UI container provided in 'run'
        if self.log_container:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] {msg}")
            self.log_container.code("\n".join(self.logs))
            print(f"[{ts}] {msg}")

    def scan_rooms(self, account):
        """Logs in and fetches the current room list."""
        rooms = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(locale="de-CH")
            page = context.new_page()
            
            try:
                page.goto("https://raumreservation.ub.unibe.ch/event/add")
                
                # Login Logic
                if "login" in page.url or "wayf" in page.url:
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
                    
                    page.wait_for_url("**/event/**", timeout=20000)

                # Select vonRoll if needed
                if "/select" in page.url:
                    try:
                        page.click("main a[href*='/set/1']")
                        page.wait_for_url("**/event/**")
                    except: pass

                # Extract Options
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
                
                rooms = page.evaluate("""() => {
                    const s = document.querySelector('#event_room');
                    if (!s) return {};
                    const r = {};
                    for (let o of s.options) { 
                        if(o.value && o.innerText) r[o.innerText.trim()] = o.value; 
                    }
                    return r;
                }""")
                
            except Exception as e:
                print(f"Scan error: {e}")
            finally:
                browser.close()
        return rooms

    def execute_booking(self, date_str, start, end, target_rooms, accounts, is_sim, log_ui):
        self.log_container = log_ui
        self.logs = []
        
        self.log(f"Starting process for {date_str}...")

        # Calculate Time Blocks (Split > 4h)
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
        except Exception:
            self.log("Invalid time format.")
            return

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            for i, task in enumerate(tasks):
                acc = accounts[i % len(accounts)]
                self.log(f"Processing Block {i+1}: {task['start']} - {task['end']}")
                
                context = browser.new_context(locale="de-CH")
                page = context.new_page()

                try:
                    # 1. Login
                    page.goto("https://raumreservation.ub.unibe.ch/event/add")
                    
                    if "login" in page.url or "wayf" in page.url:
                        try:
                            page.wait_for_selector("input", timeout=5000)
                            if page.is_visible("input[name='j_username']"):
                                page.fill("input[name='j_username']", acc['email'])
                            elif page.is_visible("#username"):
                                page.fill("#username", acc['email'])
                            
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
                            self.log("Login failed or timed out.")
                            continue

                    # 2. Location Selection
                    if "/select" in page.url:
                        try:
                            page.click("main a[href*='/set/1']")
                            page.wait_for_url("**/event/**")
                        except: pass

                    # 3. Room Search
                    time.sleep(1)
                    # Fetch current map to match IDs
                    room_map = page.evaluate("""() => {
                        const s = document.querySelector('#event_room');
                        if (!s) return {};
                        const r = {};
                        for (let o of s.options) { if(o.value) r[o.innerText.trim()] = o.value; }
                        return r;
                    }""")

                    booked = False
                    for room_name in target_rooms:
                        if room_name in room_map:
                            room_id = room_map[room_name]
                            self.log(f"Trying: {room_name}")
                            
                            # Refresh page to be clean
                            page.goto("https://raumreservation.ub.unibe.ch/event/add")
                            time.sleep(0.5)
                            
                            # Fill Form
                            page.select_option("#event_room", value=room_id)
                            
                            page.fill("#event_startDate", f"{date_str} {task['start']}")
                            page.keyboard.press("Enter")
                            time.sleep(0.5)
                            
                            # Duration
                            t1 = datetime.datetime.strptime(task['start'], fmt)
                            t2 = datetime.datetime.strptime(task['end'], fmt)
                            dur = int((t2 - t1).total_seconds() / 60)
                            
                            page.evaluate(f"document.getElementById('event_duration').value = '{dur}'")
                            page.evaluate("document.getElementById('event_duration').dispatchEvent(new Event('change', {bubbles: true}))")
                            
                            # Title
                            page.fill("#event_title", "Study")
                            if page.is_visible('input[name="event[purpose]"][value="Other"]'):
                                page.check('input[name="event[purpose]"][value="Other"]')
                            
                            if is_sim:
                                self.log("Simulation: Booking would be successful.")
                                booked = True
                                break
                            else:
                                page.click("#event_submit")
                                try:
                                    page.wait_for_url("**/event**", timeout=5000)
                                    if "/add" not in page.url:
                                        self.log(f"Success: {room_name}")
                                        booked = True
                                        break
                                except:
                                    self.log(f"Failed: {room_name}")
                        else:
                            self.log(f"Room not found in list: {room_name}")

                    if not booked:
                        self.log("No suitable room found for this block.")

                except Exception as e:
                    self.log(f"Error: {e}")
                finally:
                    context.close()
            
            browser.close()
        self.log("Process finished.")

# --- UI LAYOUT ---

accounts, acc_logs = get_accounts()

# Header
st.header("Uni Bern Room Booker")

# Fallback / Status
if not accounts:
    st.error("No accounts found in environment variables.")
    with st.expander("Manual Emergency Login"):
        m_email = st.text_input("Email")
        m_pw = st.text_input("Password", type="password")
        if m_email and m_pw:
            accounts = [{"email": m_email, "password": m_pw}]
            st.success("Manual account ready.")
else:
    st.caption(f"System: {len(accounts)} active accounts connected.")

# 1. ROOM LIST MANAGEMENT
if "room_cache" not in st.session_state:
    st.session_state.room_cache = []

with st.expander("Room Management"):
    if st.button("Update Room List (Scan)", type="secondary", use_container_width=True):
        if not accounts:
            st.error("Need at least one account to scan.")
        else:
            with st.spinner("Scanning rooms... please wait"):
                scraper = RoomScraper()
                # Use first account for scanning
                rooms_dict = scraper.scan_rooms(accounts[0])
                if rooms_dict:
                    st.session_state.room_cache = list(rooms_dict.keys())
                    st.success(f"Found {len(rooms_dict)} rooms.")
                else:
                    st.error("Scan failed. Try again.")

# Default list if cache is empty
room_options = st.session_state.room_cache if st.session_state.room_cache else [
    "Bibliothek vonRoll: Gruppenraum 001",
    "Bibliothek vonRoll: Gruppenraum 002",
    "Bibliothek vonRoll: Gruppenraum 003",
    "Bibliothek vonRoll: Gruppenraum 004",
    "Bibliothek vonRoll: Lounge"
]

# 2. BOOKING FORM
with st.form("booking_form"):
    st.subheader("Booking Details")
    
    # Date
    d_input = st.date_input("Date", datetime.datetime.now() + datetime.timedelta(days=1))
    
    # Time (Columns)
    c1, c2 = st.columns(2)
    with c1:
        s_input = st.text_input("Start Time", "08:00")
    with c2:
        e_input = st.text_input("End Time", "18:00")
    
    # Rooms
    st.caption("Select preferred rooms (Priority: Top to Bottom)")
    sel_rooms = st.multiselect("Rooms", room_options, default=room_options[:1])
    
    # Options
    chk_sim = st.checkbox("Simulation Mode (Test only)", value=True)
    
    # Submit
    submitted = st.form_submit_button("Start Booking", type="primary", use_container_width=True)

# 3. EXECUTION
if submitted:
    if not accounts:
        st.error("No accounts available.")
    elif not sel_rooms:
        st.error("Please select at least one room.")
    else:
        log_area = st.empty()
        scraper = RoomScraper()
        scraper.execute_booking(
            d_input.strftime("%d.%m.%Y"), 
            s_input, 
            e_input, 
            sel_rooms, 
            accounts, 
            chk_sim, 
            log_area
        )
