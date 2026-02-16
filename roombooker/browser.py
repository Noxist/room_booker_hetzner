import time
import json
import os
import re
from html.parser import HTMLParser
from playwright.sync_api import sync_playwright
from .config import (
    URL_LOGIN, URL_EVENT_ADD, URL_SELECT, URL_SET_VONROLL, URL_GRID_BASE,
    URL_MY_RESERVATIONS, DEBUG_DIR, BASE_DIR, get_excessive_logging
)

# --- HELPER FUNCTIONS ---
def m2t(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def t2m(t_str):
    try: h, m = map(int, t_str.split(":")); return h * 60 + m
    except: return 0


# ========================================================================
# HTML PARSER: Parses timeline grid from HTML (works on dumps AND live)
# ========================================================================
class TimelineHTMLParser(HTMLParser):
    """
    Parses the room reservation timeline HTML to extract:
    - Opening hours (from timeline-cell-clickable without timeline-closed)
    - Per-room open/closed slots
    - Existing bookings (from rect[data-event-event-value])
    """
    def __init__(self):
        super().__init__()
        # Opening hours detection
        self._all_open_hours = set()    # all data-hour values of open cells
        self._all_closed_hours = set()  # all data-hour values of closed cells
        
        # Per-room tracking
        self._current_room_id = None
        self._current_room_name = None
        self._in_room_label = False
        self._room_data = {}  # room_name -> {"open_hours": set(), "room_id": str}
        
        # Booking events
        self._events = []  # list of parsed event dicts
        
        # State
        self._in_timeline_row = False
        self._capture_room_name = False
        self._room_name_buffer = ""
    
    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        cls = attr_dict.get("class", "")
        
        # Detect room row: <div class="...timeline-row" data-timeline-target="room" data-room-id="10">
        if tag == "div" and "timeline-row" in cls and attr_dict.get("data-timeline-target") == "room":
            self._current_room_id = attr_dict.get("data-room-id")
            self._in_timeline_row = True
            self._capture_room_name = True
            self._room_name_buffer = ""
        
        # Detect timeline cells
        if tag == "div" and "timeline-cell-clickable" in cls:
            data_hour = attr_dict.get("data-hour")
            if data_hour is not None:
                try:
                    hour_val = float(data_hour)
                except ValueError:
                    return
                
                is_closed = "timeline-closed" in cls
                
                if is_closed:
                    self._all_closed_hours.add(hour_val)
                else:
                    self._all_open_hours.add(hour_val)
                    # Track per-room
                    if self._current_room_name:
                        if self._current_room_name not in self._room_data:
                            self._room_data[self._current_room_name] = {
                                "open_hours": set(),
                                "room_id": self._current_room_id,
                            }
                        self._room_data[self._current_room_name]["open_hours"].add(hour_val)
        
        # Detect booking events: <rect data-event-event-value="{...}">
        if tag == "rect" and "data-event-event-value" in attr_dict:
            try:
                ev = json.loads(attr_dict["data-event-event-value"])
                self._events.append(ev)
            except (json.JSONDecodeError, TypeError):
                pass
    
    def handle_data(self, data):
        if self._capture_room_name and self._in_timeline_row:
            text = data.strip()
            if text and re.match(r'^[AD]-\d+', text):
                # Extract just the room code, e.g. "A-204" from "A-204 (16)"
                match = re.match(r'([AD]-\d+)', text)
                if match:
                    self._current_room_name = match.group(1)
                    self._capture_room_name = False
    
    def handle_endtag(self, tag):
        pass
    
    def get_opening_hours(self):
        """Returns (min_hour_minutes, max_hour_minutes) e.g. (480, 1260) for 08:00-21:00"""
        if not self._all_open_hours:
            return None
        min_h = min(self._all_open_hours)
        max_h = max(self._all_open_hours)
        # min_h is start; max_h is the last open half-hour, so end = max_h + 0.5 hour
        open_start = int(min_h * 60)
        open_end = int((max_h + 0.5) * 60)  # +30min because each cell is 30min
        return (open_start, open_end)
    
    def get_opening_hours_formatted(self):
        """Returns ('08:00', '21:00') style tuple"""
        hours = self.get_opening_hours()
        if not hours:
            return None
        return (m2t(hours[0]), m2t(hours[1]))
    
    def get_open_slot_count(self):
        """Number of distinct open half-hour slots (across all rooms)."""
        return len(self._all_open_hours)
    
    def get_events(self):
        """Return parsed booking events."""
        return self._events
    
    def get_room_availability(self, allowed_rooms=None):
        """
        Returns {room_name: [(start_min, end_min), ...]} of FREE (bookable) time ranges.
        Considers both open hours and existing bookings.
        """
        opening = self.get_opening_hours()
        if not opening:
            return {}
        
        oh_start, oh_end = opening
        
        # Build per-room booked ranges from events
        room_bookings = {}
        for ev in self._events:
            rn = ev.get("roomName", "")
            if allowed_rooms and rn not in allowed_rooms:
                continue
            start_str = ev.get("start", "")
            end_str = ev.get("end", "")
            try:
                s_time = start_str.split("T")[1][:5]
                e_time = end_str.split("T")[1][:5]
                s_min = t2m(s_time)
                e_min = t2m(e_time)
                room_bookings.setdefault(rn, []).append((s_min, e_min))
            except:
                continue
        
        # For each room, compute free slots
        target_rooms = allowed_rooms or list(self._room_data.keys())
        availability = {}
        
        for room in target_rooms:
            booked = sorted(room_bookings.get(room, []))
            free = []
            cursor = oh_start
            for bs, be in booked:
                if bs > cursor:
                    free.append((cursor, bs))
                cursor = max(cursor, be)
            if cursor < oh_end:
                free.append((cursor, oh_end))
            availability[room] = free
        
        return availability


def parse_html_grid(html_content):
    """Parse HTML content and return a TimelineHTMLParser with results."""
    parser = TimelineHTMLParser()
    parser.feed(html_content)
    return parser

class BrowserEngine:
    def __init__(self, headless=True):
        self.headless = headless

    def _perform_login_logic(self, page, email, password):
        print(f"     [LOGIN] Starte Login für {email}...")
        try:
            page.goto(URL_LOGIN, timeout=60000)
            
            try:
                page.wait_for_load_state("domcontentloaded")
            except:
                pass
            
            time.sleep(2)
            
            # Standort Fix
            if "select" in page.url or page.locator("text=Bibliothek wählen").count() > 0:
                 print("     [NAV] Standortwahl erkannt. Setze vonRoll...")
                 page.goto(URL_SET_VONROLL) 
                 time.sleep(1)
                 page.goto(URL_LOGIN)
                 
                 try:
                     page.wait_for_load_state("domcontentloaded")
                 except:
                     pass
                 time.sleep(3)

            if "/event/add" in page.url and "wayf" not in page.url and "login" not in page.url:
                return True
            
            if page.locator("text=Login").count() > 0: 
                page.click("text=Login")
                time.sleep(2)
            
            # Edu-ID
            if "wayf" in page.url or "login" in page.url or "eduid" in page.url:
                page.wait_for_selector("#username", state="visible", timeout=10000)
                page.fill("#username", email)
                page.keyboard.press("Enter")
                
                page.wait_for_selector("#password", state="visible", timeout=10000)
                time.sleep(1) 
                page.fill("#password", password)
                page.keyboard.press("Enter")
                
                page.wait_for_url("**/event/**", timeout=30000)
                print("     [LOGIN] Erfolgreich!")
                return True
        except Exception as e:
            print(f"     [LOGIN ERROR] {e}")
        return False

    def scan_grid(self, date_str, allowed_rooms):
        """Scan the live grid page. Returns {room: [bookings]} and opening hours."""
        from .utils import normalize_date_str
        date_str = normalize_date_str(date_str)
        d_parts = date_str.split(".")
        iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
        data = {r: [] for r in allowed_rooms}
        opening_hours = None
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
            page = browser.new_page()
            try:
                url = f"{URL_GRID_BASE}{iso_date}"
                page.goto(url)
                time.sleep(1)
                if "select" in page.url: 
                    page.goto(URL_SET_VONROLL)
                    page.goto(url)
                    time.sleep(1)
                
                # Get raw HTML and parse with our parser
                html_content = page.content()
                parser = parse_html_grid(html_content)
                opening_hours = parser.get_opening_hours()
                
                # Extract events per room
                for ev in parser.get_events():
                    r = ev.get('roomName', '')
                    if r in data:
                        try:
                            s = t2m(ev['start'].split('T')[1][:5])
                            e = t2m(ev['end'].split('T')[1][:5])
                            data[r].append({"start": s, "end": e})
                        except:
                            pass
                
                # Save dump for debugging
                try:
                    dump_path = BASE_DIR / "debug_dumps" / f"{iso_date}_dump.html"
                    with open(dump_path, "w") as f:
                        f.write(html_content)
                except:
                    pass
                
                if get_excessive_logging():
                    oh = parser.get_opening_hours_formatted()
                    if oh:
                        print(f"     [GRID] {date_str} Opening Hours: {oh[0]} - {oh[1]}")
                    print(f"     [GRID] {date_str} Events found: {len(parser.get_events())}")
                
            except Exception as e:
                print(f"     [GRID ERROR] {e}")
            finally: 
                browser.close()
        return data, opening_hours

    def scan_grid_from_html(self, html_content, allowed_rooms=None):
        """Parse a local HTML dump file (for testing/verification)."""
        parser = parse_html_grid(html_content)
        opening_hours = parser.get_opening_hours()
        
        data = {}
        for ev in parser.get_events():
            r = ev.get('roomName', '')
            if allowed_rooms and r not in allowed_rooms:
                continue
            try:
                s = t2m(ev['start'].split('T')[1][:5])
                e = t2m(ev['end'].split('T')[1][:5])
                data.setdefault(r, []).append({"start": s, "end": e})
            except:
                pass
        
        return data, opening_hours

    def perform_booking(self, date_str, room, start_m, end_m, account):
        from .utils import normalize_date_str
        date_str = normalize_date_str(date_str)
        success = False
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
            page = browser.new_page()
            try:
                if not self._perform_login_logic(page, account['email'], account['password']):
                    print(f"     [BOOKING] Login failed for {account['email']}")
                    return False
                
                page.goto(URL_EVENT_ADD)
                page.wait_for_selector("#event_room", timeout=30000)
                
                # Select room by matching option text (e.g. "A-204 (16)")
                room_selected = page.evaluate(f"""(r) => {{ 
                    const s = document.querySelector('#event_room'); 
                    for(let i=0; i<s.options.length; i++) {{ 
                        if(s.options[i].innerText.includes(r)) {{ 
                            s.selectedIndex = i; 
                            s.dispatchEvent(new Event('change')); 
                            return true;
                        }} 
                    }}
                    return false;
                }}""", room)
                
                if not room_selected:
                    print(f"     [BOOKING] Raum {room} nicht im Dropdown gefunden!")
                    return False
                
                time.sleep(0.5)
                
                # Fill start date + time
                page.fill("#event_startDate", f"{date_str} {m2t(start_m)}")
                page.keyboard.press("Enter")
                time.sleep(0.5)
                
                # Fill duration in minutes
                page.fill("#event_duration", str(end_m - start_m))
                page.keyboard.press("Enter")
                
                # Title and purpose
                page.fill("#event_title", "Lernen")
                try:
                    page.check('input[name="event[purpose]"][value="Other"]')
                except:
                    pass
                
                # Store URL before submission
                url_before = page.url
                
                # Submit
                page.click("#event_submit")
                
                # Wait for page to respond
                time.sleep(3)
                
                url_after = page.url
                
                # === ROBUST ERROR DETECTION ===
                # 1. Check for VISIBLE error indicators (not substring in full HTML)
                visible_errors = []
                
                # Check for alert-danger / flash error divs
                error_selectors = [
                    '.alert-danger',
                    '.alert-error', 
                    '.form-error',
                    '.invalid-feedback:visible',
                    '.has-error .help-block',
                    '.flash-error',
                    '.error-message',
                ]
                for sel in error_selectors:
                    try:
                        els = page.locator(sel)
                        count = els.count()
                        if count > 0:
                            for i in range(count):
                                txt = els.nth(i).text_content()
                                if txt and txt.strip():
                                    visible_errors.append(txt.strip())
                    except:
                        pass
                
                # Check for form validation errors (visible text containing keywords)
                try:
                    body_text = page.locator("body").text_content().lower()
                    # Only check visible text, not HTML source
                    has_fehler = "fehler" in body_text
                    has_nicht_verfuegbar = "nicht verfügbar" in body_text or "nicht verfugbar" in body_text
                    has_belegt = "belegt" in body_text and "bereits" in body_text
                    has_ueberschneidung = "überschneidung" in body_text or "überlappung" in body_text
                except:
                    has_fehler = False
                    has_nicht_verfuegbar = False
                    has_belegt = False
                    has_ueberschneidung = False
                
                # 2. Check for success indicators
                url_changed = url_after != url_before
                redirected_away = "event/add" not in url_after
                
                # Try to detect success message in visible text
                try:
                    has_success = any(kw in body_text for kw in ["erfolgreich", "successfully", "gespeichert", "erstellt"])
                except:
                    has_success = False
                
                # 3. Decision logic
                if visible_errors:
                    print(f"     [BOOKING] Sichtbare Fehler: {'; '.join(visible_errors[:3])}")
                    success = False
                elif has_nicht_verfuegbar or has_belegt or has_ueberschneidung:
                    reason = "nicht verfügbar" if has_nicht_verfuegbar else ("belegt" if has_belegt else "Überschneidung")
                    print(f"     [BOOKING] Raum {room}: {reason}")
                    success = False
                elif has_fehler:
                    print(f"     [BOOKING] Formular-Fehler auf Seite erkannt")
                    success = False
                elif has_success or redirected_away:
                    success = True
                    print(f"     [BOOKING] Erfolgreich: {room} {m2t(start_m)}-{m2t(end_m)}")
                elif url_changed:
                    # URL changed but no clear success/error — likely success
                    success = True
                    print(f"     [BOOKING] Wahrscheinlich erfolgreich (URL geaendert): {room} {m2t(start_m)}-{m2t(end_m)}")
                else:
                    # Still on event/add, no visible errors — could be a JS-based submit
                    # Save debug info
                    print(f"     [BOOKING] Unklarer Status fuer {room} -- pruefe genauer...")
                    success = False
                
                # Always save debug screenshot & HTML on failure
                if not success:
                    ts = int(time.time())
                    try:
                        page.screenshot(path=f"{DEBUG_DIR}/error_{ts}.png")
                        with open(f"{DEBUG_DIR}/error_{ts}.html", "w") as f:
                            f.write(page.content())
                        print(f"     [DEBUG] Screenshot + HTML gespeichert: error_{ts}")
                    except:
                        pass
                    
            except Exception as e:
                print(f"     [BOOKING ERROR] {e}")
                try:
                    page.screenshot(path=f"{DEBUG_DIR}/error_{int(time.time())}.png")
                except:
                    pass
            finally: 
                browser.close()
        return success

    def get_my_reservations(self, account):
        bookings = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            try:
                if self._perform_login_logic(page, account['email'], account['password']):
                    target_url = URL_MY_RESERVATIONS
                    print(f"     [SCAN] Navigiere zu: {target_url}")
                    page.goto(target_url)
                    
                    try:
                        page.wait_for_load_state("networkidle")
                    except:
                        pass
                    
                    time.sleep(3) # Warten auf Tabelle
                    
                    # Holt alle Zellen-Texte der Tabelle
                    rows_data = page.evaluate("""() => {
                        return Array.from(document.querySelectorAll("table tbody tr")).map(row => {
                            return Array.from(row.querySelectorAll("td")).map(td => td.innerText.trim());
                        });
                    }""")
                    
                    print(f"     [SCAN] {len(rows_data)} Zeilen gefunden.")
                    
                    for cols in rows_data:
                        if not cols or len(cols) < 3: 
                            continue
                        
                        date_str = ""
                        start_time = ""
                        end_time = ""
                        room = ""
                        
                        # 1. Datum finden (DD.MM.YYYY) - FIX: Nur das Datum extrahieren!
                        for c in cols:
                            match = re.search(r"(\d{2}\.\d{2}\.\d{4})", c)
                            if match:
                                date_str = match.group(1) # Nur das Datum, ignoriere den Rest
                                break
                        
                        # 2. Zeiten finden (HH:MM)
                        times = []
                        for c in cols:
                            matches = re.findall(r"\d{2}:\d{2}", c)
                            times.extend(matches)
                        
                        if len(times) >= 2:
                            start_time = times[0]
                            end_time = times[1]
                        
                        # 3. Raum finden
                        for c in cols:
                            if "A-" in c or "D-" in c:
                                match = re.search(r"[AD]-\d+", c)
                                if match: room = match.group(0)
                                else: room = c
                                break
                        
                        if date_str and start_time and end_time and room:
                            print(f"     [FOUND] {date_str} {start_time}-{end_time} {room}")
                            bookings.append({
                                "date": date_str,
                                "start": start_time,
                                "end": end_time,
                                "room": room,
                                "account": account['email']
                            })
            except Exception as e: 
                print(f"     [SCAN ERROR] {e}")
            finally: 
                browser.close()
        
        self._save_to_debug_cache(bookings)
        return bookings

    def _save_to_debug_cache(self, new_bookings):
        cache_file = BASE_DIR / "last_scan.json"
        existing = []
        if cache_file.exists():
            try:
                with open(cache_file, "r") as f: existing = json.load(f)
            except: pass
        
        # Duplikate vermeiden
        existing_signatures = {f"{x['date']}_{x['start']}_{x['room']}_{x['account']}" for x in existing}
        for b in new_bookings:
            sig = f"{b['date']}_{b['start']}_{b['room']}_{b['account']}"
            if sig not in existing_signatures:
                existing.append(b)
        
        try:
            with open(cache_file, "w") as f: json.dump(existing, f, indent=2)
            print(f"     [DEBUG] Cache aktualisiert.")
        except: pass

    def delete_booking(self, date_str, start_m, end_m, account):
        """Delete a single booking from the reservation website."""
        results = self.delete_bookings_batch(
            [(date_str, start_m, end_m)], account
        )
        return results[0] if results else False

    def delete_bookings_batch(self, bookings_list, account):
        """
        Delete multiple bookings in a single browser session (one login).
        bookings_list: list of (date_str, start_m, end_m) tuples.
        Returns a list of booleans indicating success for each booking.
        """
        from .utils import normalize_date_str

        results = [False] * len(bookings_list)
        if not bookings_list:
            return results

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_page()
            try:
                if not self._perform_login_logic(page, account['email'], account['password']):
                    print(f"     [DELETE] Login fehlgeschlagen fuer {account['email']}")
                    return results

                # Auto-accept confirmation dialogs
                page.on("dialog", lambda dialog: dialog.accept())

                for idx, (date_str, start_m, end_m) in enumerate(bookings_list):
                    date_str = normalize_date_str(date_str)
                    start_time = f"{start_m // 60:02d}:{start_m % 60:02d}"

                    try:
                        page.goto(URL_MY_RESERVATIONS)
                        try:
                            page.wait_for_load_state("networkidle", timeout=10000)
                        except Exception:
                            pass
                        time.sleep(2)

                        print(f"     [DELETE] Suche: {date_str} ab {start_time}...")
                        target_row = (
                            page.locator("tr")
                            .filter(has_text=date_str)
                            .filter(has_text=start_time)
                        )
                        count = target_row.count()

                        if count == 0:
                            print(f"     [DELETE] Keine Reservation fuer {date_str} {start_time}")
                            continue

                        if count > 1:
                            print(f"     [DELETE] {count} Zeilen -- loesche erste")

                        delete_btn = target_row.first.locator(
                            "button", has_text="Löschen"
                        )
                        if delete_btn.is_visible():
                            delete_btn.click()
                            try:
                                page.wait_for_load_state("networkidle", timeout=10000)
                            except Exception:
                                pass
                            time.sleep(1)
                            print(f"     [DELETE] Reservation geloescht: {date_str} {start_time}")
                            results[idx] = True
                        else:
                            print(f"     [DELETE] Loeschen-Button nicht sichtbar")
                    except Exception as e:
                        print(f"     [DELETE ERROR] {date_str} {start_time}: {e}")

            except Exception as e:
                print(f"     [DELETE ERROR] Session: {e}")
            finally:
                browser.close()

        return results
