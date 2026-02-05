import base64
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional

from playwright.sync_api import sync_playwright
from roombooker.booking_engine import BookingEngine
from roombooker.server_logger import ServerLogger
from roombooker.storage import load_accounts, load_jobs, load_rooms, resolve_data_dir
from roombooker.config import URLS

# --- AI CONFIG ---
PREFERRED_ROOMS = ["D-204", "A-204", "A-241", "D-239", "D-231", "A-231", "D-202"]

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def ask_gpt4_vision(image_path, target_start, target_end, logger):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.log("⚠️ AI übersprungen: Kein API Key.")
        return None

    base64_image = encode_image(image_path)
    rooms_json = json.dumps(PREFERRED_ROOMS)

    prompt_text = f"""
    You are analysing a university room reservation timeline.
    
    Rules:
    1. Rows are rooms.
    2. Colored bars = OCCUPIED.
    3. White space = FREE.
    4. Ignore the grey past area on the left.

    Task: Find free slots from {target_start} to {target_end}.
    Only consider: {rooms_json}

    Strategy:
    1. Try finding ONE room for the full duration.
    2. If not possible, split into MAX 2 rooms to cover the full time.

    STRICT: Even small overlaps invalidate a room.
    
    Output JSON ONLY:
    [
      {{"start": "HH:MM", "end": "HH:MM", "room": "RoomName"}}
    ]
    If no valid plan exists, return [].
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": "gpt-4o", 
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }
        ],
        "max_tokens": 800
    }

    try:
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", headers=headers, data=json.dumps(payload).encode('utf-8'))
        with urllib.request.urlopen(req) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            content = res_json['choices'][0]['message']['content']
            content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(content)
    except Exception as e:
        logger.log(f"⚠️ AI Fehler: {e}")
        return None

def get_ai_plan(date_str, start_time, end_time, accs, logger) -> Optional[List[dict]]:
    """Macht Screenshot und fragt AI. Gibt Plan oder None zurück."""
    data_dir = resolve_data_dir()
    screenshot_path = "temp_scan.png"
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            # Session Reuse Versuch
            session_file = data_dir / f"session_{accs[0].email.replace('@','_')}.json"
            if session_file.exists():
                context = browser.new_context(storage_state=str(session_file), viewport={"width": 1920, "height": 2000})
            else:
                context = browser.new_context(viewport={"width": 1920, "height": 2000})
            
            page = context.new_page()
            
            # Datum parsen für URL
            d_parts = date_str.split(".")
            iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
            url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            
            logger.log(f"🤖 AI Scan für {date_str}...")
            page.goto(url)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            # Login Fallback
            if "login" in page.url or "wayf" in page.url:
                logger.log("🤖 AI Scan: Muss einloggen...")
                if page.locator("#username").is_visible():
                    page.fill("#username", accs[0].email)
                    page.keyboard.press("Enter")
                    time.sleep(2)
                    page.fill("#password", accs[0].password)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("networkidle")
                    context.storage_state(path=str(session_file))
                    page.goto(url)
                    time.sleep(2)

            # Standortwahl Fix
            if "/select" in page.url or "Standort" in page.title():
                page.goto("https://raumreservation.ub.unibe.ch/set/1")
                time.sleep(1)
                page.goto(url)
                time.sleep(2)

            # Screenshot
            time.sleep(5) # Renderzeit
            page.mouse.wheel(0, 200)
            page.screenshot(path=screenshot_path)
            browser.close()
            
            # AI Fragen
            return ask_gpt4_vision(screenshot_path, start_time, end_time, logger)

    except Exception as e:
        logger.log(f"⚠️ AI Scan fehlgeschlagen (Browser): {e}")
        return None

def main():
    logger = ServerLogger()
    data_dir = resolve_data_dir()
    
    accs = load_accounts(data_dir / "settings.json")
    if not accs:
        logger.log("Keine Accounts.")
        return

    jobs = load_jobs(data_dir / "jobs.json")
    # Mapping Wochentage auf Daten (vereinfacht für heute + 14 Tage)
    # Hier nehmen wir einfach die Jobs und prüfen, welches Datum passt.
    
    # Hilfsfunktion um Job-Datum zu finden (wie in main_headless)
    def resolve_date(day_name):
        map = {"Montag":0, "Dienstag":1, "Mittwoch":2, "Donnerstag":3, "Freitag":4, "Samstag":5, "Sonntag":6}
        target = map.get(day_name)
        if target is None: return None
        today = date.today()
        for i in range(15): # Nächste 2 Wochen
            d = today + timedelta(days=i)
            if d.weekday() == target:
                return d.strftime("%d.%m.%Y")
        return None

    all_rooms_map = load_rooms(data_dir / "rooms.json")
    engine = BookingEngine(logger)
    
    for job in jobs:
        if not job.active: continue
        
        job_date = resolve_date(job.day)
        if not job_date: continue
        
        # Check Datumslimit (14 Tage)
        d_obj = datetime.strptime(job_date, "%d.%m.%Y").date()
        if d_obj > (date.today() + timedelta(days=14)):
            continue

        logger.log(f"--- BEARBEITE {job.day} ({job_date}) ---")

        # 1. VERSUCH: AI SCAN
        logger.log("🚀 Starte AI Analyse...")
        ai_plan = get_ai_plan(job_date, job.start, job.end, accs, logger)
        
        tasks_to_execute = []
        is_ai_mode = False

        if ai_plan and len(ai_plan) > 0:
            logger.log(f"✅ AI hat einen Plan gefunden mit {len(ai_plan)} Slots!")
            is_ai_mode = True
            # Wir bauen Tasks exakt nach AI Vorgabe
            for slot in ai_plan:
                room_name = slot.get("room")
                # Prüfen ob Raum im System bekannt ist
                if not all_rooms_map.get(room_name):
                     logger.log(f"⚠️ AI wollte '{room_name}', aber Raum-ID unbekannt. Ignoriere Slot.")
                     continue
                
                # WICHTIG: Wir erstellen eine Task, in der NUR dieser eine Raum erlaubt ist
                # Das zwingt die Engine, diesen zu buchen.
                tasks_to_execute.append({
                    "start": slot["start"],
                    "end": slot["end"],
                    "date": job_date,
                    "all_rooms": all_rooms_map,
                    "forced_room": room_name # Custom Flag für unsere Logik unten
                })
        else:
            logger.log("❌ AI fand nichts oder Fehler. Falle zurück auf Standard-Logik.")
            # Standard Tasks erstellen (wie bisher)
            # Wir splitten in 4h Blöcke (oder nehmen den ganzen Tag, Engine regelt das)
            # Hier vereinfacht: Wir übergeben den ganzen Block und lassen die Engine stückeln
            # Eigentlich splittet main_headless.py in 4h Blöcke. Machen wir das auch:
            curr = datetime.strptime(job.start, "%H:%M")
            end = datetime.strptime(job.end, "%H:%M")
            while curr < end:
                nxt = curr + timedelta(hours=4)
                if nxt > end: nxt = end
                tasks_to_execute.append({
                    "start": curr.strftime("%H:%M"),
                    "end": nxt.strftime("%H:%M"),
                    "date": job_date,
                    "all_rooms": all_rooms_map
                })
                curr = nxt

        # 2. AUSFÜHRUNG
        if is_ai_mode:
            # Spezial-Modus für AI Plan
            for task in tasks_to_execute:
                # Wir rufen execute_booking auf, übergeben aber als "preferred_rooms"
                # NUR den einen Raum, den die AI wollte.
                forced_r = task["forced_room"]
                logger.log(f"🤖 AI-Befehl: Buche {forced_r} von {task['start']} bis {task['end']}")
                engine.execute_booking([task], accs, [forced_r], False, job.summary)
        else:
            # Standard Modus (Iteriert Liste durch)
            logger.log("🔄 Starte Standard-Buchung (Liste von oben nach unten)...")
            engine.execute_booking(tasks_to_execute, accs, job.rooms, False, job.summary)

if __name__ == "__main__":
    main()
