import base64
import json
import os
import sys
import time
import glob
import urllib.request
import urllib.error
from playwright.sync_api import sync_playwright
from roombooker.storage import load_accounts, resolve_data_dir
from roombooker.config import URLS

# --- KONFIGURATION ---
TARGET_START = "08:00"
TARGET_END = "20:00"
PREFERRED_ROOMS = ["D-204", "A-204", "A-241", "D-239", "D-231", "A-231", "D-202"]

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def ask_gpt4_vision(image_path):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ FEHLER: OPENAI_API_KEY ist nicht gesetzt.")
        return None

    print(f"ℹ️ Sende Bild ({os.path.getsize(image_path)} bytes) an OpenAI...")
    base64_image = encode_image(image_path)
    
    # JSON-String für den Prompt vorbereiten
    rooms_json = json.dumps(PREFERRED_ROOMS)

    # --- OPTIMIERTER PROMPT START ---
    prompt_text = f"""
    You are analysing a university room reservation timeline.

    Interpretation Rules (VERY IMPORTANT):
    1. Time runs horizontally from left to right.
    2. Each row represents one room.
    3. Colored bars represent OCCUPIED time.
    4. Completely empty white space represents FREE time.
    5. The grey area on the far left represents past time and must be ignored.
    6. The colored sector labels (red, blue, green sectors) DO NOT indicate availability. They only group rooms.

    Your task:
    Find free availability for the full time range:
    START = {TARGET_START}
    END = {TARGET_END}

    Only consider these rooms:
    {rooms_json}

    ---

    STRICT VALIDATION RULES:
    • A room is valid only if there is NO colored bar overlapping ANY part of the required time.
    • Even a small overlap invalidates the room.
    • Availability must be continuous.

    ---

    PLANNING STRATEGY:
    Step 1:
    Try to find ONE room that is free for the entire time range.

    Step 2:
    If impossible, split into MAXIMUM TWO rooms.

    When splitting:
    • Minimize the number of switches.
    • Prefer longest continuous blocks.
    • Prefer earlier switch instead of multiple short segments.

    ---

    OUTPUT REQUIREMENTS:

    Return ONLY valid JSON.

    Rules:
    • Use exact room names.
    • Use 24h time format HH:MM.
    • The combined slots MUST cover the full range.
    • Slots MUST be sorted by time.
    • No overlaps.
    • No gaps.

    Before generating the result, internally verify availability in 30 minute increments across the timeline.
    If you are uncertain about availability of a slot, treat it as OCCUPIED.
    Double check that every returned time block is fully free in the image.

    Example valid output:
    [
      {{"start": "08:00", "end": "14:00", "room": "D-204"}},
      {{"start": "14:00", "end": "20:00", "room": "A-241"}}
    ]

    If NO valid solution exists return:
    []
    """
    # --- OPTIMIERTER PROMPT ENDE ---

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
        "max_tokens": 1000
    }

    try:
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", headers=headers, data=json.dumps(payload).encode('utf-8'))
        with urllib.request.urlopen(req) as response:
            raw_body = response.read().decode('utf-8')
            try:
                result = json.loads(raw_body)
                content = result['choices'][0]['message']['content']
                # Clean Markdown
                content = content.replace("```json", "").replace("```", "").strip()
                return json.loads(content)
            except Exception as e:
                print(f"❌ OpenAI Antwort war kein gültiges JSON: {e}")
                print(f"Raw Body: {raw_body}")
                return None
    except urllib.error.HTTPError as e:
        print(f"❌ API Fehler {e.code}: {e.read().decode('utf-8')}")
        return None
    except Exception as e:
        print(f"❌ Netzwerk Fehler: {e}")
        return None

def find_session_file(data_dir):
    files = list(data_dir.glob("session_*.json"))
    if files:
        print(f"ℹ️ Nutze existierende Session: {files[0].name}")
        return files[0]
    return None

def run_visual_scan(target_date_str):
    print(f"--- 🤖 AI PLANNER FÜR {target_date_str} ---")
    data_dir = resolve_data_dir()
    accs = load_accounts(data_dir / "settings.json")
    if not accs: 
        print("❌ Keine Accounts.")
        return

    session_path = find_session_file(data_dir)

    with sync_playwright() as p:
        print("Starte Browser...")
        browser = p.chromium.launch(headless=True)
        if session_path:
             context = browser.new_context(storage_state=str(session_path), viewport={"width": 1920, "height": 2000})
        else:
             context = browser.new_context(viewport={"width": 1920, "height": 2000})
        
        page = context.new_page()

        try:
            d_parts = target_date_str.split(".")
            iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
            target_url = f"https://raumreservation.ub.unibe.ch/event?day={iso_date}"
            
            print(f"Navigiere zu: {target_url}")
            page.goto(target_url)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            # --- FORCE STANDORTWAHL ---
            if "/select" in page.url or "Standort" in page.title():
                print("ℹ️ Standort-Auswahl erkannt. Erzwinge Navigation zu 'vonRoll'...")
                page.goto("https://raumreservation.ub.unibe.ch/set/1")
                page.wait_for_load_state("networkidle")
                time.sleep(1)
                print("Zurück zum Kalender...")
                page.goto(target_url)
                time.sleep(2)

            # --- LOGIN CHECK ---
            if "login" in page.url or "wayf" in page.url or "eduid" in page.url:
                print("⚠️ Nicht eingeloggt. Führe Login durch...")
                if page.locator("#username").is_visible():
                    page.fill("#username", accs[0].email)
                    page.keyboard.press("Enter")
                    time.sleep(2)
                    page.fill("#password", accs[0].password)
                    page.keyboard.press("Enter")
                    page.wait_for_load_state("networkidle")
                    
                    new_session = data_dir / f"session_{accs[0].email.replace('@','_')}.json"
                    context.storage_state(path=str(new_session))
                    
                    print("Login fertig. Navigiere erneut zum Datum...")
                    page.goto(target_url)
                    time.sleep(3)

            print(f"🔍 Aktuelle URL: {page.url}")
            
            if "/select" in page.url:
                 print("❌ Fehler: Hängen immer noch bei Standortwahl fest.")
                 return

            print("Warte auf Kalender-Rendering (8s)...")
            time.sleep(8) 
            
            # Screenshot
            page.mouse.wheel(0, 200) 
            time.sleep(1)
            screenshot_path = "schedule_scan.png"
            page.screenshot(path=screenshot_path)
            print(f"📸 Screenshot erstellt: {screenshot_path}")
            
        except Exception as e:
            print(f"❌ Browser Fehler: {e}")
            browser.close()
            return

        browser.close()

        print("🧠 Sende Bild an OpenAI...")
        plan = ask_gpt4_vision(screenshot_path)
        
        if plan:
            print("\n✅ AI VORSCHLAG:")
            print(json.dumps(plan, indent=2))
        else:
            print("❌ Keine Antwort oder keine freien Räume.")

if __name__ == "__main__":
    import sys
    import datetime
    target = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    if len(sys.argv) > 1:
        target = sys.argv[1]
    run_visual_scan(target)
