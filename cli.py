from datetime import datetime, timedelta
from roombooker.jobs import JobManager
from roombooker.utils import (
    smart_parse_date, smart_parse_time, parse_time_to_minutes,
    format_minutes_to_time, check_overlap, build_overlap_options,
)
from roombooker.storage import StorageManager
from roombooker.browser import BrowserEngine
from main import run_booking_logic

def clean_time(t_str):
    return t_str.replace(".", ":").strip()


def _handle_overlap(date_input, start, end, category, accs, mode, freq=None,
                     interval=None, interval_unit=None):
    """
    Check for overlaps and let the user choose a resolution.
    Returns True if the booking should proceed with possibly modified params,
    or False if skipped.
    Also returns the (possibly modified) start, end, category.
    """
    overlaps = check_overlap(date_input, start, end, category)
    if not overlaps:
        return True, start, end, category

    options, meta = build_overlap_options(date_input, start, end, category, overlaps)

    print("\n" + "!" * 50)
    print("  UEBERLAPPUNG ERKANNT")
    print("!" * 50)
    print(f"\nNeue Buchung: {date_input} {start}-{end} (Kategorie: {category})")
    print("Bestehende Buchungen:")
    m2t = format_minutes_to_time
    for b in overlaps:
        print(f"  {m2t(int(b['start']))}-{m2t(int(b['end']))} {b.get('room', '?')} "
              f"({b.get('category', '?')}) [{b.get('account', '?')}]")

    print("\nOptionen:")
    for i, opt in enumerate(options, 1):
        print(f"\n  [{i}] {opt['label']}")
        print(f"      {opt['description']}")

    choice_num = input(f"\nWahl [1-{len(options)}]: ").strip()
    try:
        choice_idx = int(choice_num) - 1
        if choice_idx < 0 or choice_idx >= len(options):
            raise ValueError
    except ValueError:
        print("Ungueltige Wahl. Ueberspringe Buchung.")
        return False, start, end, category

    choice_key = options[choice_idx]['key']
    sm = StorageManager()

    if choice_key == 'skip':
        print("Buchung uebersprungen.")
        return False, start, end, category

    elif choice_key == 'replace_extend':
        _cli_delete_overlaps(sm, date_input, start, end, category)
        start = m2t(meta['combined_start'])
        end = m2t(meta['combined_end'])
        print(f"Erweiterter Zeitblock: {start}-{end}")
        return True, start, end, category

    elif choice_key == 'book_overlap':
        print("Buche trotz Ueberlappung.")
        return True, start, end, category

    elif choice_key == 'book_in_existing_cat':
        new_cat = meta['overlap_cat']
        print(f"Buche in Kategorie: {new_cat}")
        return True, start, end, new_cat

    elif choice_key == 'adjust_around':
        segments = meta['adjusted_segments']
        if not segments:
            print("Keine freien Segmente vorhanden.")
            return False, start, end, category
        print(f"Buche {len(segments)} Segment(e):")
        for seg_s, seg_e in segments:
            seg_start = m2t(seg_s)
            seg_end = m2t(seg_e)
            print(f"  -> {seg_start}-{seg_end}")
            run_booking_logic(date_input, seg_start, seg_end, category, accs)
        return False, start, end, category  # Already booked segments

    elif choice_key == 'delete_book_b':
        _cli_delete_overlaps(sm, date_input, start, end, category)
        print("Bestehende Buchungen geloescht. Buche nur B.")
        return True, start, end, category

    return True, start, end, category


def _cli_delete_overlaps(sm, date_str, start, end, new_category):
    """Delete overlapping bookings from website and local history."""
    start_m = parse_time_to_minutes(start)
    end_m = parse_time_to_minutes(end)
    history = sm.get_history()
    day_bookings = history.get(date_str, [])

    to_delete = []
    remaining = []
    for b in day_bookings:
        b_start = int(b.get('start', 0))
        b_end = int(b.get('end', 0))
        b_cat = b.get('category', 'default')
        if b_start < end_m and b_end > start_m and b_cat != new_category:
            to_delete.append(b)
        else:
            remaining.append(b)

    if to_delete:
        accounts = sm.get_settings()
        acc_map = {a['email']: a for a in accounts}
        browser = BrowserEngine(headless=True)
        by_account = {}
        for b in to_delete:
            email = b.get('account', '')
            if email in acc_map:
                by_account.setdefault(email, []).append(b)

        for email, bookings in by_account.items():
            batch = [(date_str, int(b['start']), int(b['end'])) for b in bookings]
            results = browser.delete_bookings_batch(batch, acc_map[email])
            for i, b in enumerate(bookings):
                if results[i]:
                    bid = b.get('id')
                    if bid:
                        try:
                            from roombooker.calendar_sync import CalendarSync
                            cal = CalendarSync()
                            cal.delete_event_by_booking_id(bid)
                        except Exception as ce:
                            print(f"  [CAL] Kalender-Loeschung fehlgeschlagen: {ce}")

    if date_str in history:
        history[date_str] = remaining
        if not remaining:
            del history[date_str]
        sm.save_history(history)


def interactive_wizard(mode="once"):
    print("\n" + "="*30)
    print(f"   WIZARD ({mode.upper()})")
    print("="*30)

    d_def = datetime.now().strftime("%d.%m.%Y")
    date_raw = input(f"Datum ({d_def}): ").strip() or d_def
    date_input = smart_parse_date(date_raw)
    
    start = smart_parse_time(input("Start (08:00): ").strip() or "08:00")
    end = smart_parse_time(input("Ende  (12:00): ").strip() or "12:00")

    # Load categories dynamically from categories.json
    sm = StorageManager()
    cats = sm.get_categories()
    cat_keys = list(cats.keys())

    print("\nKategorie:")
    for i, k in enumerate(cat_keys, 1):
        title = cats[k].get('title', k)
        desc = cats[k].get('desc', '')
        rooms_count = len(cats[k].get('rooms', []))
        print(f"  [{i}] {title} ({rooms_count} Raeume) {('- ' + desc) if desc else ''}")
    c = input(f"Wahl [1-{len(cat_keys)}]: ").strip()
    try:
        category = cat_keys[int(c) - 1]
    except (ValueError, IndexError):
        category = "default"

    accs = 4

    if mode == "once":
        proceed, start, end, category = _handle_overlap(
            date_input, start, end, category, accs, mode
        )
        if proceed:
            print(f"\nStarte Sofort-Buchung fuer {date_input} {start}-{end}...")
            run_booking_logic(date_input, start, end, category, accs)
    else:
        jm = JobManager()
        print("\nWiederholung:")
        print(" [1] Taeglich")
        print(" [2] Woechentlich")
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

        # Check overlap before creating job
        proceed, start, end, category = _handle_overlap(
            date_input, start, end, category, accs, mode,
            freq=freq, interval=interval, interval_unit=interval_unit
        )
        if not proceed:
            return
        
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
        print(f"Naechster Termin: {date_input}")
        
        if input("\nErsten Termin sofort buchen? (y/n): ").lower() == "y":
            run_booking_logic(date_input, start, end, category, accs, job_id)


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

    # Group by account -- batch delete (one login per account)
    by_account = {}
    for d, s, e, acc, booking in deletions:
        email = acc['email']
        if email not in by_account:
            by_account[email] = []
        by_account[email].append((d, s, e, acc, booking))

    browser = BrowserEngine(headless=True)
    deleted_count = 0

    for email, items in by_account.items():
        print(f"\n--- Account: {email} ({len(items)} Loeschungen, ein Login) ---")
        batch = [(d, s, e) for d, s, e, _, _ in items]
        results = browser.delete_bookings_batch(batch, items[0][3])

        for i, (d, s, e, acc, booking) in enumerate(items):
            if results[i]:
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
            else:
                print(f"  [FEHLER] {d} {s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d} konnte nicht geloescht werden")

    print(f"\nFertig: {deleted_count}/{len(deletions)} Buchungen geloescht.")
