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


def parse_time_to_minutes(time_str):
    """Convert HH:MM to minutes since midnight"""
    try:
        if ':' in time_str:
            h, m = time_str.split(':')
            return int(h) * 60 + int(m)
        return int(time_str) * 60  # assume hours only
    except:
        return 0


def format_minutes_to_time(minutes):
    """Convert minutes since midnight to HH:MM"""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"
