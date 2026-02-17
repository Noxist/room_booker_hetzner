import os
import sys
import threading
import logging
import io
from collections import deque, defaultdict
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# Project imports
from roombooker.config import BASE_DIR, STATUS_FILE, LOG_FILE
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from roombooker.utils import smart_parse_date, smart_parse_time
from main import run_booking_logic, run_sync


# === LOG CAPTURE: Redirect print() + logging to a file ===
class TeeWriter:
    """Write to both original stream and a log file."""
    def __init__(self, original, log_path):
        self.original = original
        self.log_path = log_path
    
    def write(self, text):
        if text.strip():  # Skip blank lines
            try:
                import datetime
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(self.log_path, "a") as f:
                    for line in text.rstrip('\n').split('\n'):
                        if line.strip():
                            f.write(f"{ts} | {line}\n")
            except:
                pass
        self.original.write(text)
    
    def flush(self):
        self.original.flush()

# Install TeeWriter for stdout and stderr
sys.stdout = TeeWriter(sys.__stdout__, str(LOG_FILE))
sys.stderr = TeeWriter(sys.__stderr__, str(LOG_FILE))

# Logging Setup (also writes to the same log file)
log_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
log_handler_stdout = logging.StreamHandler(sys.__stdout__)
log_handler_stdout.setFormatter(log_formatter)

log_handler_file = logging.FileHandler(str(LOG_FILE))
log_handler_file.setFormatter(log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[log_handler_stdout, log_handler_file]
)

# Load environment variables
load_dotenv()

# Flask App Setup
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Global lock to prevent concurrent booking threads from racing on accounts
_booking_lock = threading.Lock()



# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    """Main dashboard page"""
    sm = StorageManager()
    categories = sm.get_categories() or {}
    return render_template('index.html', categories=categories)


@app.route('/api/status')
def get_status():
    """Get current status of booking operations (auto-expires after 60s)"""
    if STATUS_FILE.exists():
        try:
            import time as _time
            with open(STATUS_FILE, "r") as f:
                raw = f.read().strip()
            parts = raw.split("|")
            if len(parts) >= 2:
                state, msg = parts[0], parts[1]
                # Check timestamp (3rd field) — expire after 60 seconds
                if len(parts) >= 3:
                    try:
                        ts = int(parts[2])
                        age = int(_time.time()) - ts
                        if age > 60 and state in ("success", "error", "warning"):
                            return jsonify({"state": "idle", "msg": "Bereit"})
                    except:
                        pass
                elif state in ("success", "error", "warning"):
                    # No timestamp = old format => always show as idle
                    return jsonify({"state": "idle", "msg": "Bereit"})
                return jsonify({"state": state, "msg": msg})
        except Exception as e:
            logging.error(f"Error reading status file: {e}")
    return jsonify({"state": "idle", "msg": "Bereit"})


@app.route('/book', methods=['POST'])
def book():
    """Start a new booking or create a job"""
    try:
        date = request.form.get('date', '').strip()
        start = request.form.get('start', '').strip()
        end = request.form.get('end', '').strip()
        category = request.form.get('category', 'default')
        frequency = request.form.get('frequency', 'onetime')
        
        logging.info(f"Booking request: date={date}, start={start}, end={end}, cat={category}, freq={frequency}")
        
        # Validation
        if not date or not start or not end:
            flash('Daten fehlen! Bitte alle Felder ausfüllen.', 'danger')
            logging.warning("Booking validation failed: missing fields")
            return redirect(url_for('index'))
        
        # Handle recurring bookings by creating a job
        if frequency in ['weekly', 'daily', 'monthly', 'custom']:
            jm = JobManager()
            
            # Handle custom intervals
            job_name = f"Serie {date} {start}-{end}"
            if frequency == 'custom':
                interval = int(request.form.get('interval', 1))
                interval_unit = request.form.get('interval_unit', 'weeks')
                job_name = f"Alle {interval} {interval_unit}"
            
            job_id = jm.create_job(
                name=job_name,
                date_str=date,
                start=start,
                end=end,
                category=category,
                accounts=4,
                repetition=frequency,
                interval=int(request.form.get('interval', 1)) if frequency == 'custom' else None,
                interval_unit=request.form.get('interval_unit', 'weeks') if frequency == 'custom' else None
            )
            flash(f'Wiederkehrender Job erstellt. Naechste Buchung: {date}', 'success')
            logging.info(f"Created recurring job: {job_id}")
        
        # For one-time bookings: check overlap and start immediately
        if frequency == 'onetime':
            # Check for booking conflicts before starting
            sm = StorageManager()
            history = sm.get_history()
            
            # Parse date and times for conflict check
            from roombooker.utils import parse_time_to_minutes
            start_min = parse_time_to_minutes(start)
            end_min = parse_time_to_minutes(end)
            
            # Check if this exact timeframe is already booked
            date_bookings = history.get(date, [])
            has_conflict = False
            for booking in date_bookings:
                if booking.get('start') <= start_min < booking.get('end') or \
                   booking.get('start') < end_min <= booking.get('end'):
                    has_conflict = True
                    flash(f'Zeitslot {start}-{end} teilweise bereits gebucht. Pruefe Verfuegbarkeit...', 'warning')
                    break
            
            if not has_conflict:
                flash(f'Einmalige Buchung gestartet fuer {date} {start}-{end}', 'info')
            
            # Start booking in background
            logging.info(f"Starting immediate booking for {date} {start}-{end}")
            threading.Thread(
                target=run_booking_logic, 
                args=(date, start, end, category, 4, None),
                daemon=True
            ).start()
        
    except Exception as e:
        logging.error(f"Error in book route: {e}", exc_info=True)
        flash(f'Fehler: {str(e)}', 'danger')
    
    return redirect(url_for('index'))


@app.route('/sync')
def sync():
    """Sync all bookings from accounts"""
    threading.Thread(target=run_sync, daemon=True).start()
    flash('Synchronisierung gestartet!', 'info')
    return redirect(url_for('index'))


@app.route('/jobs')
def jobs():
    """View all active jobs"""
    jm = JobManager()
    active_jobs = [j for j in jm.jobs if j.get('active', True)]
    return render_template('jobs.html', jobs=active_jobs)


@app.route('/jobs/delete/<job_id>')
def delete_job(job_id):
    """Delete a job by ID and clean up its calendar placeholders"""
    try:
        jm = JobManager()
        jm.jobs = [j for j in jm.jobs if j.get('id') != job_id]
        jm.save_jobs()

        # Clean up calendar placeholder events for this job
        try:
            from roombooker.config import CREDENTIALS_FILE
            if CREDENTIALS_FILE.exists():
                from roombooker.calendar_sync import CalendarSync
                cal = CalendarSync()
                deleted_count = cal.delete_events_by_job_id(job_id)
                if deleted_count > 0:
                    flash(f'Job {job_id} geloescht + {deleted_count} Kalender-Platzhalter entfernt!', 'success')
                else:
                    flash(f'Job {job_id} geloescht!', 'success')
            else:
                flash(f'Job {job_id} geloescht!', 'success')
        except Exception as e:
            logging.warning(f"Calendar cleanup for job {job_id} failed: {e}")
            flash(f'Job {job_id} geloescht (Kalender-Cleanup fehlgeschlagen)!', 'warning')

        logging.info(f"Deleted job: {job_id}")
    except Exception as e:
        flash(f'Fehler beim Loeschen: {str(e)}', 'danger')
        logging.error(f"Error deleting job {job_id}: {e}")
    return redirect(url_for('jobs'))


@app.route('/jobs/toggle/<job_id>')
def toggle_job(job_id):
    """Toggle job active status"""
    try:
        jm = JobManager()
        for job in jm.jobs:
            if job.get('id') == job_id:
                job['active'] = not job.get('active', True)
                break
        jm.save_jobs()
        flash('Job-Status geändert!', 'info')
    except Exception as e:
        flash(f'Fehler: {str(e)}', 'danger')
    return redirect(url_for('jobs'))


@app.route('/accounts', methods=['GET', 'POST'])
def accounts():
    """Manage booking accounts"""
    sm = StorageManager()
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Email und Passwort erforderlich!', 'danger')
            return redirect(url_for('accounts'))
        
        accounts_list = sm.get_settings()
        new_account = {
            "email": email, 
            "password": password, 
            "active": True
        }
        accounts_list.append(new_account)
        sm.save_settings(accounts_list)
        flash('Account erfolgreich hinzugefügt!', 'success')
        return redirect(url_for('accounts'))
    
    return render_template('accounts.html', accounts=sm.get_settings())


@app.route('/accounts/delete/<int:idx>')
def delete_account(idx):
    """Delete an account by index"""
    sm = StorageManager()
    accounts_list = sm.get_settings()
    
    if 0 <= idx < len(accounts_list):
        deleted = accounts_list.pop(idx)
        sm.save_settings(accounts_list)
        flash(f'Account {deleted.get("email", "unknown")} gelöscht!', 'success')
    else:
        flash('Ungültiger Account Index!', 'danger')
    
    return redirect(url_for('accounts'))


@app.route('/logs')
def logs():
    """View logs page"""
    return render_template('logs.html')


@app.route('/api/logs')
def api_logs():
    """Get real-time application logs from log file"""
    try:
        lines = int(request.args.get('lines', 500))
    except:
        lines = 500
    
    try:
        if LOG_FILE.exists():
            # Read last N lines efficiently
            with open(LOG_FILE, 'r') as f:
                all_lines = f.readlines()
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return "".join(tail), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        else:
            return "Log-Datei noch nicht vorhanden. Warte auf erste Aktivität...\n", 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f"ERROR: {str(e)}", 500, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/api/logs/clear', methods=['POST'])
def api_logs_clear():
    """Clear the log file"""
    try:
        with open(LOG_FILE, 'w') as f:
            f.write("")
        print("[LOGS] Log-Datei geloescht")
        return "OK", 200
    except Exception as e:
        return f"ERROR: {str(e)}", 500


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page with proxy configuration"""
    sm = StorageManager()
    from roombooker.config import SETTINGS_FILE

    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'proxy':
            raw = sm._load(SETTINGS_FILE, {})
            if not isinstance(raw, dict):
                raw = {"accounts": raw}
            raw["proxy"] = {
                "enabled": request.form.get('proxy_enabled') == 'on',
                "socks_host": request.form.get('socks_host', '').strip(),
                "socks_port": int(request.form.get('socks_port', 1080) or 1080),
                "username": request.form.get('proxy_username', '').strip(),
                "password": request.form.get('proxy_password', '').strip(),
                "local_port": int(request.form.get('local_port', 18123) or 18123),
            }
            sm._save(SETTINGS_FILE, raw)
            flash('Proxy-Einstellungen gespeichert!', 'success')
        return redirect(url_for('settings'))

    raw = sm._load(SETTINGS_FILE, {})
    proxy = {}
    if isinstance(raw, dict):
        proxy = raw.get('proxy', {})
    return render_template('settings.html', proxy=proxy)


# ============================================
# SCHEDULER & STARTUP
# ============================================

def check_scheduled_jobs():
    """
    Background job checker with 14-day booking window logic.
    Groups jobs by target_date so same-day jobs run sequentially,
    preventing race conditions on accounts.
    """
    try:
        from datetime import datetime, timedelta

        jm = JobManager()
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        max_date = (today + timedelta(days=14))

        logging.info(f"[SCHEDULER] Pruefe {len(jm.jobs)} Jobs  |  buchbar bis {max_date.strftime('%d.%m.%Y')}")

        # Group eligible jobs by target date
        jobs_by_date = defaultdict(list)

        for job in jm.jobs:
            if not job.get('active', True):
                continue

            target_date_str = job.get('target_date') or job.get('date_str', '')
            if not target_date_str:
                continue

            try:
                from roombooker.utils import normalize_date_str
                target_date_str = normalize_date_str(target_date_str)
                target_date = datetime.strptime(target_date_str, "%d.%m.%Y")

                if not (today < target_date <= max_date):
                    continue

                last_booked = job.get('last_booked')
                if last_booked == target_date_str:
                    logging.debug(f"Job {job.get('id')} already booked for {target_date_str}")
                    continue

                jobs_by_date[target_date_str].append(job)
            except Exception as e:
                logging.error(f"Error processing job {job.get('id')}: {e}")

        # Run jobs grouped by date, sequentially within each date
        for date_str, date_jobs in sorted(jobs_by_date.items()):
            if len(date_jobs) > 1:
                logging.info(f"[SCHEDULER] {len(date_jobs)} Jobs am {date_str} -- sequenzielle Ausfuehrung")

            def _run_date_jobs(d_str, d_jobs):
                with _booking_lock:
                    for job in d_jobs:
                        logging.info(f"[SCHEDULER] Starte Job: {job.get('name', job.get('id'))} fuer {d_str}")
                        try:
                            run_booking_logic(
                                d_str,
                                job.get('start', job.get('time_start', '08:00')),
                                job.get('end', job.get('time_end', '12:00')),
                                job.get('category', 'default'),
                                4,
                                job.get('id')
                            )
                        except Exception as e:
                            logging.error(f"Job {job.get('id')} failed: {e}")
                        import time
                        time.sleep(2)

            threading.Thread(
                target=_run_date_jobs,
                args=(date_str, date_jobs),
                daemon=True
            ).start()

            import time
            time.sleep(1)

    except Exception as e:
        logging.error(f"Error in scheduled job check: {e}", exc_info=True)


if __name__ == '__main__':
    # ── Start proxy forwarder if configured ──
    from roombooker.config import get_proxy_config
    _proxy_cfg = get_proxy_config()
    if _proxy_cfg:
        from roombooker.proxy_forwarder import start_forwarder
        start_forwarder(
            _proxy_cfg["socks_host"],
            _proxy_cfg["socks_port"],
            _proxy_cfg["username"],
            _proxy_cfg["password"],
            _proxy_cfg["local_port"],
        )
        logging.info("Proxy forwarder started → socks5://%s:%d (local :%d)",
                      _proxy_cfg["socks_host"], _proxy_cfg["socks_port"],
                      _proxy_cfg["local_port"])
    else:
        logging.info("No proxy configured – direct connections")

    # Initialize background scheduler for automatic jobs
    # Run daily at 00:15 to check for bookings (14-day window logic)
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Europe/Zurich'))
    
    # Daily job execution at 00:15
    scheduler.add_job(
        check_scheduled_jobs, 
        'cron', 
        hour=0, 
        minute=15,
        id='daily_booking_check'
    )
    
    # Also run every hour for monitoring/debugging
    scheduler.add_job(
        check_scheduled_jobs,
        'interval',
        hours=1,
        id='hourly_check'
    )
    
    scheduler.start()
    
    logging.info("=" * 50)
    logging.info("Starting RoomBooker Web UI")
    logging.info("Server: 0.0.0.0:5000")
    logging.info("Scheduler: Daily at 00:15 + hourly checks")
    logging.info("=" * 50)
    
    # ── One-time: fix existing calendar events + sync pending jobs ──
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

    t = threading.Thread(target=_startup_calendar_sync, daemon=True)
    t.start()
    
    # Start Flask application
    app.run(host='0.0.0.0', port=5000, use_reloader=False, debug=False)
