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
    if len(parts) == 3:
        return f"{int(parts[0]):02d}.{int(parts[1]):02d}.{int(parts[2])}"
    return user_input


def normalize_date_str(date_str):
    """Ensure date_str is always DD.MM.YYYY format. Handles DD.MM shorthand."""
    parts = date_str.strip().split(".")
    if len(parts) == 2:
        year = datetime.now().year
        return f"{int(parts[0]):02d}.{int(parts[1]):02d}.{year}"
    if len(parts) == 3:
        return f"{int(parts[0]):02d}.{int(parts[1]):02d}.{int(parts[2])}"
    return date_str

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


def check_overlap(date_str, start_time, end_time, category_key):
    """
    Check if a new booking (start_time-end_time, category_key) overlaps with
    existing bookings on date_str that belong to a DIFFERENT category.

    Returns a list of overlapping bookings (dicts from history) or [].
    """
    from .storage import StorageManager
    date_str = normalize_date_str(date_str)
    start_m = parse_time_to_minutes(start_time) if isinstance(start_time, str) else int(start_time)
    end_m = parse_time_to_minutes(end_time) if isinstance(end_time, str) else int(end_time)

    sm = StorageManager()
    history = sm.get_history()
    day_bookings = history.get(date_str, [])

    overlaps = []
    for b in day_bookings:
        b_start = int(b.get('start', 0))
        b_end = int(b.get('end', 0))
        b_cat = b.get('category', 'default')

        # Time overlap: A.start < B.end AND A.end > B.start
        if b_start < end_m and b_end > start_m and b_cat != category_key:
            overlaps.append(b)

    return overlaps


def build_overlap_options(date_str, start_time, end_time, category_key, overlaps):
    """
    Build the 6 overlap resolution options with concrete times and category names.
    Returns a list of dicts with 'key', 'label', 'description'.
    """
    from .storage import StorageManager
    sm = StorageManager()
    cats = sm.get_categories()

    start_m = parse_time_to_minutes(start_time) if isinstance(start_time, str) else int(start_time)
    end_m = parse_time_to_minutes(end_time) if isinstance(end_time, str) else int(end_time)

    m2t = format_minutes_to_time
    new_cat_title = cats.get(category_key, {}).get('title', category_key)

    # Aggregate overlapping bookings
    overlap_start = min(int(b['start']) for b in overlaps)
    overlap_end = max(int(b['end']) for b in overlaps)
    overlap_cat = overlaps[0].get('category', 'default')
    overlap_cat_title = cats.get(overlap_cat, {}).get('title', overlap_cat)

    # Combined window for option 2 (replace & extend)
    combined_start = min(start_m, overlap_start)
    combined_end = max(end_m, overlap_end)

    # Adjusted window for option 5 (book around existing)
    # Find free segments of [start_m, end_m] that don't overlap with any existing booking
    adjusted_segments = []
    cursor = start_m
    sorted_overlaps = sorted(overlaps, key=lambda b: int(b['start']))
    for b in sorted_overlaps:
        b_s = int(b['start'])
        b_e = int(b['end'])
        if cursor < b_s:
            adjusted_segments.append((cursor, b_s))
        cursor = max(cursor, b_e)
    if cursor < end_m:
        adjusted_segments.append((cursor, end_m))
    adjusted_str = ", ".join(f"{m2t(s)}-{m2t(e)}" for s, e in adjusted_segments) or "keine freien Segmente"

    overlap_desc = ", ".join(
        f"{m2t(int(b['start']))}-{m2t(int(b['end']))} {b.get('room', '?')} ({cats.get(b.get('category',''), {}).get('title', b.get('category','?'))})"
        for b in overlaps
    )

    options = [
        {
            "key": "skip",
            "label": "Ueberspringen",
            "description": (
                f"Buchung B ({m2t(start_m)}-{m2t(end_m)}, {new_cat_title}) NICHT buchen. "
                f"Bestehende Buchungen bleiben: {overlap_desc}."
            ),
        },
        {
            "key": "replace_extend",
            "label": "Ersetzen & Erweitern",
            "description": (
                f"Bestehende Buchung(en) loeschen ({overlap_desc}). "
                f"Neuen Zeitblock {m2t(combined_start)}-{m2t(combined_end)} in Kategorie {new_cat_title} buchen."
            ),
        },
        {
            "key": "book_overlap",
            "label": "Trotzdem buchen (Ueberlappung)",
            "description": (
                f"Buchung B ({m2t(start_m)}-{m2t(end_m)}, {new_cat_title}) buchen. "
                f"Bestehende Buchung(en) bleiben. Ueberlappung wird akzeptiert."
            ),
        },
        {
            "key": "book_in_existing_cat",
            "label": f"B in Kategorie {overlap_cat_title} buchen",
            "description": (
                f"Buchung B ({m2t(start_m)}-{m2t(end_m)}) buchen, aber in Kategorie "
                f"{overlap_cat_title} statt {new_cat_title}. Bestehende Buchung(en) bleiben."
            ),
        },
        {
            "key": "adjust_around",
            "label": "B anpassen (freie Teile)",
            "description": (
                f"Nur den freien Teil buchen: {adjusted_str} in Kategorie {new_cat_title}. "
                f"Bestehende Buchung(en) bleiben unveraendert."
            ),
        },
        {
            "key": "delete_book_b",
            "label": "A loeschen, nur B buchen",
            "description": (
                f"Bestehende Buchung(en) loeschen ({overlap_desc}). "
                f"Nur B ({m2t(start_m)}-{m2t(end_m)}, {new_cat_title}) buchen."
            ),
        },
    ]

    return options, {
        "overlap_cat": overlap_cat,
        "combined_start": combined_start,
        "combined_end": combined_end,
        "adjusted_segments": adjusted_segments,
    }
