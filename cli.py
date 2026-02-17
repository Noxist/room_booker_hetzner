from datetime import datetime, timedelta
from roombooker.jobs import JobManager
from roombooker.utils import smart_parse_date, smart_parse_time, parse_time_to_minutes
from roombooker.storage import StorageManager
from roombooker.browser import BrowserEngine
from main import run_booking_logic

def clean_time(t_str):
    return t_str.replace(".", ":").strip()

def interactive_wizard(mode="once"):
    print("\n" + "="*30)
    print(f"   WIZARD ({mode.upper()})")
    print("="*30)

    d_def = datetime.now().strftime("%d.%m.%Y")
    date_raw = input(f"Datum ({d_def}): ").strip() or d_def
    date_input = smart_parse_date(date_raw)
    
    start = smart_parse_time(input("Start (08:00): ").strip() or "08:00")
    end = smart_parse_time(input("Ende  (12:00): ").strip() or "12:00")

    print("\nKategorie:")
    print("  [1] Grosser Raum (16 Pers.)")
    print("  [2] Standard (10 Pers.)")
    print("  [3] Klein (6 Pers.)")
    cat_map = {"1": "large", "2": "medium", "3": "small"}
    c = input("Wahl [2]: ").strip() or "2"
    category = cat_map.get(c, "medium")

    accs = 4

    if mode == "once":
        print(f"\nStarte Sofort-Buchung fuer {date_input} {start}-{end}...")
        run_booking_logic(date_input, start, end, category, accs)
    else:
        jm = JobManager()
        print("\nWiederholung:")
        print(" [1] Täglich")
        print(" [2] Wöchentlich")
        print(" [3] Monatlich")
        print(" [4] Benutzerdefiniert")
        f = input("Wahl [2]: ").strip() or "2"
        
        freq_map = {"1": "daily", "2": "weekly", "3": "monthly", "4": "custom"}
        freq = freq_map.get(f, "weekly")
        
        interval = 1
        interval_unit = "weeks"
        
        if freq == "custom":
            interval = int(input("Wiederhole alle X (Zahl): ").strip() or "1")
            print("Einheit:")
            print(" [1] Tage")
            print(" [2] Wochen")
            print(" [3] Monate")
            u = input("Wahl [2]: ").strip() or "2"
            unit_map = {"1": "days", "2": "weeks", "3": "months"}
            interval_unit = unit_map.get(u, "weeks")
        
        job_name = f"Serie {date_input} {start}-{end}"
        if freq == "custom":
            job_name = f"Alle {interval} {interval_unit}"
        
        job_id = jm.create_job(
            name=job_name, 
            date_str=date_input, 
            start=start, 
            end=end, 
            category=category, 
            accounts=accs, 
            repetition=freq,
            interval=interval if freq == "custom" else None,
            interval_unit=interval_unit if freq == "custom" else None
        )
        print(f"Job gespeichert (ID: {job_id})")
        print(f"Nächster Termin: {date_input}")
        
        if input("\nErsten Termin sofort buchen? (y/n): ").lower() == "y":
            run_booking_logic(date_input, start, end, category, accs)


def _parse_date_list(raw):
    """Parse user input into a list of date strings.
    Supports: single date, comma-separated dates, or a range with '-'.
    E.g. '20.02', '20.02, 21.02', '20.02-24.02'
    """
    raw = raw.strip()
    if not raw:
        return []

    # Range: "20.02-24.02" or "20.02.2026-24.02.2026"
    if '-' in raw and ',' not in raw:
        parts = [p.strip() for p in raw.split('-', 1)]
        if len(parts) == 2:
            d1 = smart_parse_date(parts[0])
            d2 = smart_parse_date(parts[1])
            try:
                dt1 = datetime.strptime(d1, "%d.%m.%Y")
                dt2 = datetime.strptime(d2, "%d.%m.%Y")
                dates = []
                cur = dt1
                while cur <= dt2:
                    dates.append(cur.strftime("%d.%m.%Y"))
                    cur += timedelta(days=1)
                return dates
            except:
                return [d1, d2]

    # Comma-separated
    if ',' in raw:
        return [smart_parse_date(p.strip()) for p in raw.split(',') if p.strip()]

    # Single date
    return [smart_parse_date(raw)]


def deletion_wizard():
    """Interactive wizard for deleting reservations."""
    print("\n" + "="*35)
    print("   RESERVIERUNG LOESCHEN")
    print("="*35)

    sm = StorageManager()
    history = sm.get_history()

    if not history:
        print("\nKeine Buchungen in der History vorhanden.")
        return

    # Show upcoming dates with bookings
    from roombooker.utils import normalize_date_str
    now = datetime.now()
    future_dates = []
    for d_str, bookings in sorted(history.items()):
        try:
            dt = datetime.strptime(d_str, "%d.%m.%Y")
            if dt >= now.replace(hour=0, minute=0, second=0, microsecond=0):
                future_dates.append((d_str, bookings))
        except:
            pass

    if not future_dates:
        print("\nKeine zukuenftigen Buchungen gefunden.")
        return

    print("\nZukuenftige Buchungen:")
    for d_str, bookings in future_dates:
        details = []
        for b in bookings:
            s = int(b.get('start', 0))
            e = int(b.get('end', 0))
            details.append(f"{s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d} {b.get('room','?')} ({b.get('account','?')})")
        print(f"  {d_str}: {', '.join(details)}")

    print("\nModus:")
    print("  [1] Einzelnes Datum loeschen (alle Buchungen)")
    print("  [2] Datumsbereich loeschen (z.B. 20.02-24.02)")
    print("  [3] Bestimmte Buchung loeschen (Datum + Zeit)")
    mode = input("Wahl [1]: ").strip() or "1"

    dates_to_delete = []
    time_filter = None  # None = delete all on that date

    if mode == "1":
        raw = input("Datum (z.B. 20.02): ").strip()
        dates_to_delete = _parse_date_list(raw)
    elif mode == "2":
        raw = input("Bereich (z.B. 20.02-24.02): ").strip()
        dates_to_delete = _parse_date_list(raw)
    elif mode == "3":
        raw = input("Datum (z.B. 20.02): ").strip()
        dates_to_delete = _parse_date_list(raw)
        t_raw = input("Startzeit (z.B. 10:00): ").strip()
        if t_raw:
            time_filter = parse_time_to_minutes(smart_parse_time(t_raw))

    if not dates_to_delete:
        print("Keine gueltigen Daten eingegeben.")
        return

    # Collect all deletions grouped by account (to minimize logins)
    deletions = []  # list of (date, start_m, end_m, account_dict)
    accounts = sm.get_settings()
    acc_map = {a['email']: a for a in accounts}

    for d_str in dates_to_delete:
        bookings = history.get(d_str, [])
        for b in bookings:
            s = int(b.get('start', 0))
            e = int(b.get('end', 0))
            email = b.get('account', '')
            if time_filter is not None and s != time_filter:
                continue
            if email in acc_map:
                deletions.append((d_str, s, e, acc_map[email], b))

    if not deletions:
        print("Keine passenden Buchungen gefunden.")
        return

    # Confirm
    print(f"\nFolgende {len(deletions)} Buchung(en) werden geloescht:")
    for d, s, e, acc, _ in deletions:
        print(f"  {d} {s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d} ({acc['email']})")

    confirm = input("\nFortfahren? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Abgebrochen.")
        return

    # Group by account to minimize logins
    by_account = {}
    for d, s, e, acc, booking in deletions:
        email = acc['email']
        if email not in by_account:
            by_account[email] = []
        by_account[email].append((d, s, e, acc, booking))

    browser = BrowserEngine(headless=True)
    deleted_count = 0

    for email, items in by_account.items():
        print(f"\n--- Account: {email} ({len(items)} Loeschungen) ---")
        for d, s, e, acc, booking in items:
            print(f"  Loesche: {d} {s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d}...")
            try:
                ok = browser.delete_booking(d, s, e, acc)
                if ok:
                    deleted_count += 1
                    # Remove from local history
                    h = sm.get_history()
                    if d in h:
                        h[d] = [b for b in h[d] if not (
                            int(b.get('start', -1)) == s and
                            int(b.get('end', -1)) == e and
                            b.get('account', '') == email
                        )]
                        if not h[d]:
                            del h[d]
                        sm.save_history(h)

                    # Remove from Google Calendar
                    try:
                        from roombooker.config import CREDENTIALS_FILE
                        bid = booking.get('id')
                        if CREDENTIALS_FILE.exists() and bid:
                            from roombooker.calendar_sync import CalendarSync
                            cal = CalendarSync()
                            cal.delete_event_by_booking_id(bid)
                    except Exception as ce:
                        print(f"  [CAL] Kalender-Loeschung fehlgeschlagen: {ce}")
            except Exception as ex:
                print(f"  [ERROR] {ex}")

    print(f"\nFertig: {deleted_count}/{len(deletions)} Buchungen geloescht.")
