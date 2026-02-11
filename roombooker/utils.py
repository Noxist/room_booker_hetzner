import time, random
from datetime import datetime, timedelta

def human_sleep(duration=1.0):
    time.sleep(duration * random.uniform(0.8, 1.2))

def smart_parse_date(u):
    now = datetime.now()
    u = u.strip()
    if not u: return (now + timedelta(days=1)).strftime("%d.%m.%Y")
    p = u.split(".")
    if len(p) == 2: return f"{int(p[0]):02d}.{int(p[1]):02d}.{now.year}"
    return u

def smart_parse_time(u):
    u = u.strip().replace(".", ":")
    if ":" not in u and len(u) <= 2: return f"{int(u):02d}:00"
    if ":" in u: h, m = u.split(":"); return f"{int(h):02d}:{int(m):02d}"
    return u
