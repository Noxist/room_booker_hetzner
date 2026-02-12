import os
import sys
import threading
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# Project imports
from roombooker.config import BASE_DIR, STATUS_FILE
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from roombooker.utils import smart_parse_date, smart_parse_time
from main import run_booking_logic, run_sync

# Logging Setup
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s | %(levelname)s | %(message)s', 
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Load environment variables
load_dotenv()

# Flask App Setup
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Login Manager Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class User(UserMixin):
    def __init__(self, id): 
        self.id = id


@login_manager.user_loader
def load_user(user_id): 
    return User(user_id)


@app.context_processor
def inject_user():
    """Inject current_user into all templates"""
    return dict(current_user=current_user)


# ============================================
# ROUTES
# ============================================

@app.route('/')
@login_required
def index():
    """Main dashboard page"""
    sm = StorageManager()
    categories = sm.get_categories() or {}
    return render_template('index.html', categories=categories)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        password = os.getenv("WEB_PASSWORD", "admin123")
        if request.form.get('password') == password:
            login_user(User(1))
            flash('Login erfolgreich!', 'success')
            return redirect(url_for('index'))
        flash('Falsches Passwort', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """Logout current user"""
    logout_user()
    flash('Logout erfolgreich!', 'info')
    return redirect(url_for('login'))


@app.route('/api/status')
@login_required
def get_status():
    """Get current status of booking operations"""
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r") as f:
                parts = f.read().strip().split("|", 1)
                if len(parts) == 2: 
                    return jsonify({"state": parts[0], "msg": parts[1]})
        except Exception as e:
            logging.error(f"Error reading status file: {e}")
    return jsonify({"state": "idle", "msg": "Warte auf Auftrag..."})


@app.route('/book', methods=['POST'])
@login_required
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
            flash(f'✅ Wiederkehrender Job erstellt! Nächste Buchung: {date}', 'success')
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
                    flash(f'⚠️ Zeitslot {start}-{end} teilweise bereits gebucht. Prüfe Verfügbarkeit...', 'warning')
                    break
            
            if not has_conflict:
                flash(f'🚀 Einmalige Buchung gestartet für {date} {start}-{end}', 'info')
            
            # Start booking in background
            logging.info(f"Starting immediate booking for {date} {start}-{end}")
            threading.Thread(
                target=run_booking_logic, 
                args=(date, start, end, category, 4, None),
                daemon=True
            ).start()
        
    except Exception as e:
        logging.error(f"Error in book route: {e}", exc_info=True)
        flash(f'❌ Fehler: {str(e)}', 'danger')
    
    return redirect(url_for('index'))


@app.route('/sync')
@login_required
def sync():
    """Sync all bookings from accounts"""
    threading.Thread(target=run_sync, daemon=True).start()
    flash('Synchronisierung gestartet!', 'info')
    return redirect(url_for('index'))


@app.route('/jobs')
@login_required
def jobs():
    """View all scheduled jobs (only recurring ones)"""
    jm = JobManager()
    # Filter: only show recurring jobs (weekly, daily, monthly)
    recurring_jobs = [j for j in jm.jobs if j.get('frequency') not in ['onetime', 'once'] and j.get('active', True)]
    return render_template('jobs.html', jobs=recurring_jobs)


@app.route('/jobs/delete/<job_id>')
@login_required
def delete_job(job_id):
    """Delete a job by ID"""
    try:
        jm = JobManager()
        jm.jobs = [j for j in jm.jobs if j.get('id') != job_id]
        jm.save_jobs()
        flash(f'Job {job_id} gelöscht!', 'success')
        logging.info(f"Deleted job: {job_id}")
    except Exception as e:
        flash(f'Fehler beim Löschen: {str(e)}', 'danger')
        logging.error(f"Error deleting job {job_id}: {e}")
    return redirect(url_for('jobs'))


@app.route('/jobs/toggle/<job_id>')
@login_required
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
@login_required
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
@login_required
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
@login_required
def logs():
    """View logs page"""
    return render_template('logs.html')


@app.route('/api/logs')
@login_required
def api_logs():
    """Get application logs"""
    try:
        from datetime import datetime
        # Try to read from status file and recent booking history
        logs = []
        logs.append("=== RoomBooker Application Logs ===")
        logs.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logs.append("")
        
        # Add status info
        if STATUS_FILE.exists():
            try:
                with open(STATUS_FILE, 'r') as f:
                    status = f.read().strip()
                    logs.append(f"[STATUS] {status}")
            except Exception as e:
                logs.append(f"[ERROR] Could not read status: {e}")
        else:
            logs.append("[STATUS] idle|Warte auf Auftrag...")
        logs.append("")
        
        # Add recent jobs info
        try:
            jm = JobManager()
            active_jobs = [j for j in jm.jobs if j.get('active', True)]
            logs.append(f"[JOBS] Total jobs: {len(jm.jobs)}")
            logs.append(f"[JOBS] Active jobs: {len(active_jobs)}")
            
            if active_jobs:
                logs.append("")
                logs.append("Active Jobs:")
                for job in active_jobs[:10]:  # Last 10 jobs
                    name = job.get('name', 'Unnamed')
                    date = job.get('target_date') or job.get('date_str', 'No date')
                    start = job.get('start') or job.get('time_start', '?')
                    end = job.get('end') or job.get('time_end', '?')
                    cat = job.get('category', 'default')
                    freq = job.get('frequency', 'once')
                    last = job.get('last_booked', 'Never')
                    
                    logs.append(f"  • {name}")
                    logs.append(f"    Date: {date} | {start}-{end}")
                    logs.append(f"    Category: {cat} | Frequency: {freq}")
                    logs.append(f"    Last booked: {last}")
                    logs.append("")
        except Exception as e:
            logs.append(f"[ERROR] Could not load jobs: {e}")
        
        # Add accounts info
        try:
            sm = StorageManager()
            accounts = sm.get_settings()
            active_accounts = [a for a in accounts if a.get('active', True)]
            logs.append(f"[ACCOUNTS] Total: {len(accounts)} | Active: {len(active_accounts)}")
            for acc in active_accounts:
                logs.append(f"  • {acc.get('email', 'Unknown')}")
        except Exception as e:
            logs.append(f"[ERROR] Could not load accounts: {e}")
        
        logs.append("")
        logs.append("=" * 50)
        logs.append("For detailed logs use: docker-compose logs -f app")
        
        return "\n".join(logs), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f"ERROR: {str(e)}", 500, {'Content-Type': 'text/plain; charset=utf-8'}


# ============================================
# SCHEDULER & STARTUP
# ============================================

def check_scheduled_jobs():
    """
    Background job checker with 14-day booking window logic.
    Checks which jobs need to be executed based on the 14-day advance booking rule.
    """
    try:
        from datetime import datetime, timedelta
        
        jm = JobManager()
        now = datetime.now()
        
        # 14-day window: we can book for dates that are exactly 14 days from now
        # at midnight + small buffer
        booking_date = (now + timedelta(days=14)).replace(hour=0, minute=0, second=0, microsecond=0)
        booking_date_str = booking_date.strftime("%d.%m.%Y")
        
        logging.debug(f"Scheduler check: {len(jm.jobs)} jobs, booking window: {booking_date_str}")
        
        for job in jm.jobs:
            if not job.get('active', True):
                continue
                
            target_date_str = job.get('target_date') or job.get('date_str', '')
            if not target_date_str:
                continue
            
            # Parse target date
            try:
                # Handle both DD.MM and DD.MM.YYYY formats
                parts = target_date_str.split('.')
                if len(parts) == 2:
                    target_date_str = f"{parts[0]}.{parts[1]}.{now.year}"
                
                target_date = datetime.strptime(target_date_str, "%d.%m.%Y")
                
                # Check if this job should be booked today (target is 14 days from now)
                if target_date.date() == booking_date.date():
                    # Check if already booked
                    last_booked = job.get('last_booked')
                    if last_booked == target_date_str:
                        logging.debug(f"Job {job.get('id')} already booked for {target_date_str}")
                        continue
                    
                    # Execute booking
                    logging.info(f"Executing scheduled job: {job.get('name', job.get('id'))} for {target_date_str}")
                    
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
                    
            except Exception as e:
                logging.error(f"Error processing job {job.get('id')}: {e}")
                continue
                
    except Exception as e:
        logging.error(f"Error in scheduled job check: {e}", exc_info=True)


if __name__ == '__main__':
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
    
    # Start Flask application
    app.run(host='0.0.0.0', port=5000, use_reloader=False, debug=False)
