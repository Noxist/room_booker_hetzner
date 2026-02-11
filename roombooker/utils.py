import time
import random
from datetime import datetime, timedelta

def human_sleep(duration=1.0):
    time.sleep(duration * random.uniform(0.8, 1.2))

def smart_parse_date(user_input):
    now = datetime.now()
    user_input = user_input.strip()
    if not user_input:
        return (now + timedelta(days=1)).strftime("%d.%m.%Y")
    parts = user_input.split(".")
    if len(parts) == 2:
        return f"{int(parts[0]):02d}.{int(parts[1]):02d}.{now.year}"
    return user_input

def smart_parse_time(user_input):
    user_input = user_input.strip().replace(".", ":")
    if not user_input: return ""
    if ":" not in user_input and len(user_input) <= 2:
        return f"{int(user_input):02d}:00"
    if ":" in user_input:
        h, m = user_input.split(":")
        return f"{int(h):02d}:{int(m):02d}"
    return user_input
