import os
import sys
import threading
import logging
import time as _time
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

from roombooker.config import BASE_DIR, STATUS_FILE, LOG_FILE
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from roombooker.browser import BrowserEngine
from roombooker.utils import (
    smart_parse_date, smart_parse_time, parse_time_to_minutes,
    format_minutes_to_time, check_overlap, build_overlap_options,
    normalize_date_str as util_normalize_date_str,
)


# === LOG: Tee stdout/stderr to log file ===

class TeeWriter:
    """Write to both original stream and a log file."""
    def __init__(self, original, log_path):
        self.original = original
        self.log_path = log_path

    def write(self, text):
        if text.strip():
            try:
                import datetime
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(self.log_path, "a") as f:
                    for line in text.rstrip('\n').split('\n'):
                        if not line.strip():
                            continue
                        # Skip noisy polling / static GET lines
                        if '"GET / HTTP' in line and '127.0.0.1' in line:
                            continue
                        if any(p in line for p in (
                            'GET /api/status', 'GET /api/logs',
                            'GET /static/', 'GET /favicon.ico',
                        )):
                            continue
                        f.write(f"{ts} | {line}\n")
            except Exception:
                pass
        self.original.write(text)

    def flush(self):
        self.original.flush()


sys.stdout = TeeWriter(sys.__stdout__, str(LOG_FILE))
sys.stderr = TeeWriter(sys.__stderr__, str(LOG_FILE))

log_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
log_handler_stdout = logging.StreamHandler(sys.__stdout__)
log_handler_stdout.setFormatter(log_formatter)
log_handler_file = logging.FileHandler(str(LOG_FILE))
log_handler_file.setFormatter(log_formatter)
logging.basicConfig(level=logging.INFO, handlers=[log_handler_stdout, log_handler_file])


# --- Suppress noisy Werkzeug GET request logs ---
import re as _re

_NOISY_PATHS = _re.compile(
    r'"GET /(api/status|api/logs|static/|favicon\.ico| HTTP)'
)

class _QuietRequestFilter(logging.Filter):
    """Drop routine polling / static-asset GET lines from the log."""
    def filter(self, record):
        msg = record.getMessage()
        # Keep POST, DELETE, errors, non-200 – only drop boring GETs
        if _NOISY_PATHS.search(msg):
            return False
        # Also suppress the health-check "GET / HTTP" from 127.0.0.1
        if '"GET / HTTP' in msg and '127.0.0.1' in msg:
            return False
        return True

logging.getLogger('werkzeug').addFilter(_QuietRequestFilter())

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)


# ============================================
# HELPERS
# ============================================

def set_web_status(msg, state="info"):
    try:
        ts = int(_time.time())
        with open(STATUS_FILE, "w") as f:
            f.write(f"{state}|{msg}|{ts}")
    except Exception:
        pass


def get_booking_window():
    """
    Return (window_start, window_end) as datetime objects.
    Bookable window: today 00:00 to (today + 14 days) 00:00.
    On 17.02.2026 you can book up to 02.03.2026 (last full day).
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_end = window_start + timedelta(days=14)
    return window_start, window_end


def is_date_in_booking_window(date_str):
    """Check if a date string (DD.MM.YYYY) falls within the 14-day booking window."""
    from datetime import datetime
    try:
        from roombooker.utils import normalize_date_str
        date_str = normalize_date_str(date_str)
        target = datetime.strptime(date_str, "%d.%m.%Y")
        window_start, window_end = get_booking_window()
        return window_start <= target < window_end
    except Exception:
        return False


# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    sm = StorageManager()
    categories = sm.get_categories() or {}
    return render_template('index.html', categories=categories)


@app.route('/api/status')
def get_status():
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r") as f:
                raw = f.read().strip()
            parts = raw.split("|")
            if len(parts) >= 2:
                state, msg = parts[0], parts[1]
                if len(parts) >= 3:
                    try:
                        ts = int(parts[2])
                        age = int(_time.time()) - ts
                        if age > 60 and state in ("success", "error", "warning"):
                            return jsonify({"state": "idle", "msg": "Bereit"})
                    except Exception:
                        pass
                elif state in ("success", "error", "warning"):
                    return jsonify({"state": "idle", "msg": "Bereit"})
                return jsonify({"state": state, "msg": msg})
        except Exception as e:
            logging.error(f"Error reading status file: {e}")
    return jsonify({"state": "idle", "msg": "Bereit"})


@app.route('/book', methods=['POST'])
def book():
    """Start a new booking or create a job."""
    try:
        date = request.form.get('date', '').strip()
        start = request.form.get('start', '').strip()
        end = request.form.get('end', '').strip()
        category = request.form.get('category', 'default')
        frequency = request.form.get('frequency', 'onetime')
        skip_overlap = request.form.get('skip_overlap', '') == '1'

        logging.info(f"Booking request: date={date}, start={start}, end={end}, cat={category}, freq={frequency}")

        if not date or not start or not end:
            flash('Daten fehlen! Bitte alle Felder ausfuellen.', 'danger')
            return redirect(url_for('index'))

        from roombooker.utils import normalize_date_str
        date = normalize_date_str(smart_parse_date(date))
        start = smart_parse_time(start)
        end = smart_parse_time(end)

        # --- Overlap detection (only on first submission, not after resolution) ---
        if not skip_overlap:
            overlaps = check_overlap(date, start, end, category)
            if overlaps:
                options, meta = build_overlap_options(date, start, end, category, overlaps)
                return render_template(
                    'overlap.html',
                    date=date, start=start, end=end,
                    category=category, frequency=frequency,
                    interval=request.form.get('interval', '1'),
                    interval_unit=request.form.get('interval_unit', 'weeks'),
                    overlaps=overlaps,
                    options=options,
                    meta=meta,
                )

        # Recurring bookings -> always create a job
        if frequency in ['weekly', 'daily', 'monthly', 'custom']:
            jm = JobManager()
            job_name = f"Serie {date} {start}-{end}"
            interval = None
            interval_unit = None
            if frequency == 'custom':
                interval = int(request.form.get('interval', 1))
                interval_unit = request.form.get('interval_unit', 'weeks')
                job_name = f"Alle {interval} {interval_unit}"

            job_id = jm.create_job(
                name=job_name, date_str=date, start=start, end=end,
                category=category, accounts=4, repetition=frequency,
                interval=interval, interval_unit=interval_unit
            )
            flash(f'Wiederkehrender Job erstellt (ID: {job_id}). Naechste Buchung: {date}', 'success')
            logging.info(f"Created recurring job: {job_id}")

            # Immediately check if the first occurrence is within the booking window
            if is_date_in_booking_window(date):
                logging.info(f"First occurrence {date} is in window -- booking immediately")
                from main import run_booking_logic
                threading.Thread(
                    target=run_booking_logic,
                    args=(date, start, end, category, 4, job_id),
                    daemon=True
                ).start()

            return redirect(url_for('index'))

        # One-time booking -> create a job and book if in window
        if frequency == 'onetime':
            jm = JobManager()
            job_id = jm.create_job(
                name=f"Einmalig {date} {start}-{end}",
                date_str=date, start=start, end=end,
                category=category, accounts=4, repetition='once'
            )

            if is_date_in_booking_window(date):
                flash(f'Einmalige Buchung gestartet fuer {date} {start}-{end}', 'info')
                from main import run_booking_logic
                threading.Thread(
                    target=run_booking_logic,
                    args=(date, start, end, category, 4, job_id),
                    daemon=True
                ).start()
            else:
                flash(
                    f'Datum {date} liegt ausserhalb des 14-Tage-Fensters. '
                    f'Job erstellt, wird automatisch gebucht.', 'info'
                )

    except Exception as e:
        logging.error(f"Error in book route: {e}", exc_info=True)
        flash(f'Fehler: {str(e)}', 'danger')

    return redirect(url_for('index'))


@app.route('/book/resolve', methods=['POST'])
def book_resolve():
    """Handle overlap resolution choice."""
    try:
        choice = request.form.get('choice', 'skip')
        date = request.form.get('date', '')
        start = request.form.get('start', '')
        end = request.form.get('end', '')
        category = request.form.get('category', 'default')
        frequency = request.form.get('frequency', 'onetime')
        interval = request.form.get('interval', '1')
        interval_unit = request.form.get('interval_unit', 'weeks')
        overlap_cat = request.form.get('overlap_cat', '')
        combined_start = request.form.get('combined_start', '')
        combined_end = request.form.get('combined_end', '')
        adjusted_segments = request.form.get('adjusted_segments', '')

        logging.info(f"Overlap resolution: choice={choice}, date={date}, start={start}, end={end}")

        if choice == 'skip':
            flash('Buchung uebersprungen. Keine Aenderungen.', 'info')
            return redirect(url_for('index'))

        sm = StorageManager()

        if choice == 'replace_extend':
            # Delete overlapping bookings, book combined window
            _delete_overlapping_bookings(sm, date, start, end, category)
            start = format_minutes_to_time(int(combined_start))
            end = format_minutes_to_time(int(combined_end))
            # Fall through to normal booking with skip_overlap

        elif choice == 'book_overlap':
            # Just book B as-is, no changes to existing
            pass

        elif choice == 'book_in_existing_cat':
            # Book B but in the existing category
            category = overlap_cat

        elif choice == 'adjust_around':
            # Delete overlapping bookings is NOT needed, just book the free segments
            if adjusted_segments:
                import json
                segments = json.loads(adjusted_segments)
                if not segments:
                    flash('Keine freien Segmente verfuegbar.', 'warning')
                    return redirect(url_for('index'))
                # Book each segment as a separate booking
                for seg_start, seg_end in segments:
                    seg_s = format_minutes_to_time(seg_start)
                    seg_e = format_minutes_to_time(seg_end)
                    _submit_booking(
                        date, seg_s, seg_e, category, frequency,
                        interval, interval_unit
                    )
                flash(f'{len(segments)} Segment(e) gebucht.', 'success')
                return redirect(url_for('index'))
            else:
                flash('Keine angepassten Segmente vorhanden.', 'warning')
                return redirect(url_for('index'))

        elif choice == 'delete_book_b':
            # Delete existing overlapping bookings, book only B
            _delete_overlapping_bookings(sm, date, start, end, category)

        # Submit the booking (for choices that fall through)
        _submit_booking(date, start, end, category, frequency, interval, interval_unit)

    except Exception as e:
        logging.error(f"Error in book_resolve: {e}", exc_info=True)
        flash(f'Fehler: {str(e)}', 'danger')

    return redirect(url_for('index'))


def _delete_overlapping_bookings(sm, date, start, end, new_category):
    """Delete bookings on date that overlap with start-end and are from a different category."""
    start_m = parse_time_to_minutes(start)
    end_m = parse_time_to_minutes(end)
    history = sm.get_history()
    day_bookings = history.get(date, [])

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

    # Delete from website — group by account for efficiency
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
            batch = [(date, int(b['start']), int(b['end'])) for b in bookings]
            results = browser.delete_bookings_batch(batch, acc_map[email])
            for i, b in enumerate(bookings):
                if results[i]:
                    logging.info(f"Deleted booking: {b.get('room','?')} {date} "
                                 f"{int(b['start'])//60:02d}:{int(b['start'])%60:02d} "
                                 f"({email})")

        # Clean up calendar: delete events for removed bookings
        try:
            from roombooker.calendar_sync import CalendarSync
            cal = CalendarSync()
            for b in to_delete:
                bid = b.get('id')
                if bid:
                    cal.delete_event_by_booking_id(bid)
        except Exception as ce:
            logging.warning(f"Calendar cleanup failed: {ce}")

    # Update local history
    if date in history:
        history[date] = remaining
        if not remaining:
            del history[date]
        sm.save_history(history)


def _submit_booking(date, start, end, category, frequency, interval, interval_unit):
    """Create a job and trigger booking if in window."""
    jm = JobManager()

    if frequency in ['weekly', 'daily', 'monthly', 'custom']:
        job_name = f"Serie {date} {start}-{end}"
        iv = None
        iv_unit = None
        if frequency == 'custom':
            iv = int(interval)
            iv_unit = interval_unit
            job_name = f"Alle {iv} {iv_unit}"

        job_id = jm.create_job(
            name=job_name, date_str=date, start=start, end=end,
            category=category, accounts=4, repetition=frequency,
            interval=iv, interval_unit=iv_unit
        )
        logging.info(f"Created recurring job: {job_id}")
        flash(f'Wiederkehrender Job erstellt (ID: {job_id}).', 'success')

        if is_date_in_booking_window(date):
            from main import run_booking_logic
            threading.Thread(
                target=run_booking_logic,
                args=(date, start, end, category, 4, job_id),
                daemon=True
            ).start()
    else:
        job_id = jm.create_job(
            name=f"Einmalig {date} {start}-{end}",
            date_str=date, start=start, end=end,
            category=category, accounts=4, repetition='once'
        )

        if is_date_in_booking_window(date):
            flash(f'Buchung gestartet fuer {date} {start}-{end}', 'info')
            from main import run_booking_logic
            threading.Thread(
                target=run_booking_logic,
                args=(date, start, end, category, 4, job_id),
                daemon=True
            ).start()
        else:
            flash(
                f'Datum {date} ausserhalb des 14-Tage-Fensters. Job erstellt.', 'info'
            )


@app.route('/sync')
def sync():
    from main import run_sync
    threading.Thread(target=run_sync, daemon=True).start()
    flash('Synchronisierung gestartet!', 'info')
    return redirect(url_for('index'))


# --- Jobs ---

@app.route('/jobs')
def jobs():
    jm = JobManager()
    active_jobs = [j for j in jm.jobs if j.get('active', True)]
    return render_template('jobs.html', jobs=active_jobs)


@app.route('/jobs/delete/<job_id>')
def delete_job(job_id):
    try:
        jm = JobManager()
        jm.jobs = [j for j in jm.jobs if j.get('id') != job_id]
        jm.save_jobs()
        flash(f'Job {job_id} geloescht!', 'success')
        logging.info(f"Deleted job: {job_id}")
    except Exception as e:
        flash(f'Fehler beim Loeschen: {str(e)}', 'danger')
    return redirect(url_for('jobs'))


@app.route('/jobs/toggle/<job_id>')
def toggle_job(job_id):
    try:
        jm = JobManager()
        for job in jm.jobs:
            if job.get('id') == job_id:
                job['active'] = not job.get('active', True)
                break
        jm.save_jobs()
        flash('Job-Status geaendert!', 'info')
    except Exception as e:
        flash(f'Fehler: {str(e)}', 'danger')
    return redirect(url_for('jobs'))


# --- Accounts ---

@app.route('/accounts', methods=['GET', 'POST'])
def accounts():
    sm = StorageManager()
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if not email or not password:
            flash('Email und Passwort erforderlich!', 'danger')
            return redirect(url_for('accounts'))
        accounts_list = sm.get_settings()
        accounts_list.append({"email": email, "password": password, "active": True})
        sm.save_settings(accounts_list)
        flash('Account erfolgreich hinzugefuegt!', 'success')
        return redirect(url_for('accounts'))
    return render_template('accounts.html', accounts=sm.get_settings())


@app.route('/accounts/delete/<int:idx>')
def delete_account(idx):
    sm = StorageManager()
    accounts_list = sm.get_settings()
    if 0 <= idx < len(accounts_list):
        deleted = accounts_list.pop(idx)
        sm.save_settings(accounts_list)
        flash(f'Account {deleted.get("email", "unknown")} geloescht!', 'success')
    else:
        flash('Ungueltiger Account Index!', 'danger')
    return redirect(url_for('accounts'))


# --- Categories Management ---

@app.route('/categories')
def categories_page():
    sm = StorageManager()
    cats = sm.get_categories()
    return render_template('categories.html', categories=cats)


@app.route('/categories/add', methods=['POST'])
def add_category():
    try:
        sm = StorageManager()
        cats = sm.get_categories()
        key = request.form.get('key', '').strip().lower().replace(' ', '_')
        title = request.form.get('title', '').strip()
        desc = request.form.get('desc', '').strip()
        rooms_raw = request.form.get('rooms', '').strip()
        rooms = [r.strip() for r in rooms_raw.split(',') if r.strip()]

        if not key or not title:
            flash('Schluessel und Titel erforderlich!', 'danger')
            return redirect(url_for('categories_page'))

        cats[key] = {"title": title, "desc": desc, "rooms": rooms}
        sm.save_categories(cats)
        flash(f'Kategorie "{title}" erstellt!', 'success')
    except Exception as e:
        flash(f'Fehler: {str(e)}', 'danger')
    return redirect(url_for('categories_page'))


@app.route('/categories/edit/<cat_key>', methods=['POST'])
def edit_category(cat_key):
    try:
        sm = StorageManager()
        cats = sm.get_categories()
        if cat_key not in cats:
            flash('Kategorie nicht gefunden!', 'danger')
            return redirect(url_for('categories_page'))

        title = request.form.get('title', '').strip()
        desc = request.form.get('desc', '').strip()
        rooms_raw = request.form.get('rooms', '').strip()
        rooms = [r.strip() for r in rooms_raw.split(',') if r.strip()]

        cats[cat_key]['title'] = title or cats[cat_key].get('title', cat_key)
        cats[cat_key]['desc'] = desc
        cats[cat_key]['rooms'] = rooms
        sm.save_categories(cats)
        flash(f'Kategorie "{cat_key}" aktualisiert!', 'success')
    except Exception as e:
        flash(f'Fehler: {str(e)}', 'danger')
    return redirect(url_for('categories_page'))


@app.route('/categories/delete/<cat_key>')
def delete_category(cat_key):
    try:
        sm = StorageManager()
        cats = sm.get_categories()
        if cat_key in cats:
            del cats[cat_key]
            sm.save_categories(cats)
            flash(f'Kategorie "{cat_key}" geloescht!', 'success')
        else:
            flash('Kategorie nicht gefunden!', 'danger')
    except Exception as e:
        flash(f'Fehler: {str(e)}', 'danger')
    return redirect(url_for('categories_page'))


# --- Logs ---

@app.route('/logs')
def logs():
    return render_template('logs.html')


@app.route('/api/logs')
def api_logs():
    try:
        lines = int(request.args.get('lines', 500))
    except Exception:
        lines = 500
    try:
        if LOG_FILE.exists():
            with open(LOG_FILE, 'r') as f:
                all_lines = f.readlines()
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return "".join(tail), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        else:
            return "Log-Datei noch nicht vorhanden.\n", 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f"ERROR: {str(e)}", 500, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/api/logs/clear', methods=['POST'])
def api_logs_clear():
    try:
        with open(LOG_FILE, 'w') as f:
            f.write("")
        print("[LOGS] Log-Datei geloescht")
        return "OK", 200
    except Exception as e:
        return f"ERROR: {str(e)}", 500


@app.route('/settings')
def settings():
    return render_template('settings.html')


# ============================================
# SCHEDULER
# ============================================

def check_scheduled_jobs():
    """
    Background job checker with 14-day booking window logic.

    The booking window is: today 00:00  to  (today + 14 days) 00:00.
    Any active job whose target_date falls within this window AND hasn't
    been booked yet for that date will be booked immediately.

    For recurring jobs, after a successful booking the target_date advances
    to the next occurrence (handled in JobManager.mark_done).
    """
    try:
        from datetime import datetime, timedelta
        from roombooker.utils import normalize_date_str

        jm = JobManager()
        window_start, window_end = get_booking_window()

        logging.info(
            f"[SCHEDULER] Pruefe {len(jm.jobs)} Jobs | "
            f"Fenster: {window_start.strftime('%d.%m.%Y')} - {window_end.strftime('%d.%m.%Y')}"
        )

        for job in jm.jobs:
            if not job.get('active', True):
                continue

            target_date_str = job.get('target_date') or job.get('date_str', '')
            if not target_date_str:
                continue

            try:
                target_date_str = normalize_date_str(target_date_str)
                target_date = datetime.strptime(target_date_str, "%d.%m.%Y")

                # Must be within the 14-day booking window
                if not (window_start <= target_date < window_end):
                    continue

                # Already booked for this date?
                last_booked = job.get('last_booked')
                if last_booked == target_date_str:
                    logging.debug(f"Job {job.get('id')} already booked for {target_date_str}")
                    continue

                logging.info(
                    f"[SCHEDULER] Starte Job: {job.get('name', job.get('id'))} "
                    f"fuer {target_date_str}"
                )

                from main import run_booking_logic
                threading.Thread(
                    target=run_booking_logic,
                    args=(
                        target_date_str,
                        job.get('start', job.get('time_start', '08:00')),
                        job.get('end', job.get('time_end', '12:00')),
                        job.get('category', 'default'),
                        4,
                        job.get('id')
                    ),
                    daemon=True
                ).start()

                _time.sleep(2)

            except Exception as e:
                logging.error(f"Error processing job {job.get('id')}: {e}")
                continue

    except Exception as e:
        logging.error(f"Error in scheduled job check: {e}", exc_info=True)


# ============================================
# STARTUP
# ============================================

if __name__ == '__main__':
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Europe/Zurich'))

    scheduler.add_job(
        check_scheduled_jobs, 'cron',
        hour=0, minute=15, id='daily_booking_check'
    )

    scheduler.add_job(
        check_scheduled_jobs, 'interval',
        hours=1, id='hourly_check'
    )

    scheduler.start()

    logging.info("=" * 50)
    logging.info("Starting RoomBooker Web UI")
    logging.info("Server: 0.0.0.0:5000")
    logging.info("Scheduler: Daily at 00:15 + hourly checks")
    logging.info("=" * 50)

    def _startup_calendar_sync():
        try:
            from roombooker.config import CREDENTIALS_FILE
            if CREDENTIALS_FILE.exists():
                from roombooker.calendar_sync import CalendarSync
                cal = CalendarSync()
                cal.fix_all_existing_events()
                cal.sync_all_pending_jobs()
        except Exception as e:
            logging.warning(f"Startup calendar sync failed: {e}")

    threading.Thread(target=_startup_calendar_sync, daemon=True).start()

    # Run scheduler immediately on startup
    threading.Thread(target=check_scheduled_jobs, daemon=True).start()

    app.run(host='0.0.0.0', port=5000, use_reloader=False, debug=False)
