from datetime import datetime, timedelta

def smart_parse_date(user_input):
    """
    Macht aus Eingaben ein sauberes DD.MM.YYYY
    - Leer -> Datum von morgen
    - "14.02" -> "14.02.2026" (Aktuelles Jahr)
    """
    now = datetime.now()
    user_input = user_input.strip()

    if not user_input:
        tomorrow = now + timedelta(days=1)
        return tomorrow.strftime("%d.%m.%Y")

    parts = user_input.split(".")
    if len(parts) == 2:
        return f"{int(parts[0]):02d}.{int(parts[1]):02d}.{now.year}"
    
    if len(parts) == 3:
        year = parts[2]
        if len(year) == 2: year = "20" + year
        return f"{int(parts[0]):02d}.{int(parts[1]):02d}.{year}"

    return user_input

def smart_parse_time(user_input):
    """
    Macht aus Eingaben ein sauberes HH:MM
    - "8" -> "08:00"
    - "930" -> "09:30"
    """
    user_input = user_input.strip().replace(".", ":")
    
    if not user_input: return ""

    if ":" not in user_input and len(user_input) <= 2:
        return f"{int(user_input):02d}:00"
    
    if ":" not in user_input and len(user_input) > 2:
        h = user_input[:-2]
        m = user_input[-2:]
        return f"{int(h):02d}:{int(m):02d}"

    if ":" in user_input:
        h, m = user_input.split(":")
        return f"{int(h):02d}:{int(m):02d}"

    return user_input
