from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List

from roombooker.booking_engine import BookingEngine
from roombooker.calendar_sync import CalendarSync
from roombooker.config import HARDCODED_ROOMS
from roombooker.mqtt_notifier import MqttNotifier
from roombooker.server_logger import ServerLogger
from roombooker.storage import load_accounts, load_jobs, load_rooms, resolve_data_dir


def resolve_job_date(day: str) -> str | None:
    try:
        parsed = datetime.strptime(day, "%d.%m.%Y").date()
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        pass

    weekday_map = {
        "Montag": 0,
        "Dienstag": 1,
        "Mittwoch": 2,
        "Donnerstag": 3,
        "Freitag": 4,
        "Samstag": 5,
        "Sonntag": 6,
    }
    target = weekday_map.get(day)
    if target is None:
        return None
    today = date.today()
    # Wir suchen im Bereich von heute bis +14 Tage
    for offset in range(0, 15):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() == target:
            return candidate.strftime("%d.%m.%Y")
    return None


def build_tasks(start: str, end: str, resolved_date: str, rooms: Dict[str, str]):
    tasks: List[Dict[str, object]] = []
    try:
        fmt = "%H:%M"
        current = datetime.strptime(start, fmt)
        target = datetime.strptime(end, fmt)
        while current < target:
            next_slot = current + timedelta(hours=4)
            if next_slot > target:
                next_slot = target
            tasks.append(
                {
                    "start": current.strftime(fmt),
                    "end": next_slot.strftime(fmt),
                    "date": resolved_date,
                    "all_rooms": rooms,
                }
            )
            current = next_slot
    except Exception:
        return []
    return tasks


def main() -> None:
    logger = ServerLogger()
    data_dir = resolve_data_dir()
    logger.log(f"Nutze Datenverzeichnis: {data_dir}")

    accounts = [acc for acc in load_accounts() if acc.active and acc.email]
    if not accounts:
        logger.log("Keine aktiven Accounts gefunden.")
        return

    jobs = [job for job in load_jobs() if job.active]
    if not jobs:
        logger.log("Keine aktiven Jobs gefunden.")
        return

    rooms = load_rooms() or HARDCODED_ROOMS
    if not rooms:
        logger.log("Keine Räume gefunden.")
        return

    summary = "Lernen"
    if "ROOMBOOKER_EVENT_SUMMARY" in __import__("os").environ:
        summary = __import__("os").environ["ROOMBOOKER_EVENT_SUMMARY"]

    engine = BookingEngine(logger)
    all_successes: List[Dict[str, object]] = []

    # 14-Tage-Limit berechnen
    limit_date = date.today() + timedelta(days=14)

    for job in jobs:
        resolved_date = resolve_job_date(job.day)
        if not resolved_date:
            continue
            
        # FIX: Prüfen, ob das Datum erlaubt ist (<= 14 Tage)
        job_date_obj = datetime.strptime(resolved_date, "%d.%m.%Y").date()
        if job_date_obj > limit_date:
            logger.log(f"INFO: Überspringe {resolved_date} (Limit: {limit_date.strftime('%d.%m.%Y')})")
            continue

        tasks = build_tasks(job.start, job.end, resolved_date, rooms)
        if not tasks:
            logger.log(f"Job übersprungen (ungültige Zeit): {job.start}-{job.end}")
            continue
            
        successes = engine.execute_booking(tasks, accounts, job.rooms, simulation_mode=False, summary=summary)
        all_successes.extend(successes)

    notifier = MqttNotifier(logger)
    if all_successes:
        notifier.send_status("Gebucht", f"{len(all_successes)} Slots")
    else:
        # Nur senden, wenn wir überhaupt versucht haben zu buchen (d.h. Datum war gültig)
        pass 

    credentials_path = __import__("os").environ.get(
        "GOOGLE_CREDENTIALS_PATH", str(data_dir / "google_credentials.json")
    )
    calendar_id = __import__("os").environ.get("GOOGLE_CALENDAR_ID", "")
    if not calendar_id:
        return

    calendar = CalendarSync(credentials_path, calendar_id, logger, summary=summary)
    calendar.sync_slots(all_successes)


if __name__ == "__main__":
    main()
