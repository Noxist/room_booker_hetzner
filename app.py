import os
import sys
import threading
import logging
import time
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv, set_key
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# Import Logic
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from roombooker.utils import smart_parse_date, smart_parse_time
from main import run_booking_logic, run_sync

# --- KONFIGURATION ---
DATA_DIR = "/root/auto_reserve_data"
os.environ["ROOMBOOKER_DATA_DIR"] = DATA_DIR 
ENV_FILE = ".env"

# --- LOGGING ---
class CleanLogFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "GET /api/logs" in msg: return False
        if "GET /static/" in msg: return False
        if "GET /logs" in msg: return False
        return True

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler("log.txt"),
        logging.StreamHandler(sys.stdout)
    ]
)
for h in logging.getLogger().handlers: h.addFilter(CleanLogFilter())
logging.getLogger('werkzeug').addFilter(CleanLogFilter())

# --- FLASK ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id): self.id = id

@login_manager.user_loader
def load_user(user_id): return User(user_id)

# --- EXECUTION ---
def safe_run_booking(date_str, start_str, end_str, cat, count, job_id=None):
    logging.info(f"[EXEC] >>> Start: {date_str} ({start_str}-{end_str}) [Job: {job_id}]")
    try:
        if not os.path.exists(os.path.join(DATA_DIR, "categories.json")):
            logging.error("[EXEC] FEHLER: categories.json fehlt!")
            return
        run_booking_logic(date_str, start_str, end_str, cat, count, job_id)
        logging.info("[EXEC] <<< Fertig.")
    except Exception as e:
        logging.error(f"[EXEC] CRASH: {e}", exc_info=True)

# --- SCHEDULER ---
def check_scheduled_jobs():
    logging.info("[SCHEDULER] Prüfe Jobs...")
    try:
        jm = JobManager()
        due = jm.get_due_jobs()
        if not due: return
        logging.info(f"[SCHEDULER] {len(due)} Jobs fällig.")
        for job, t_date in due:
            threading.Thread(target=safe_run_booking, args=(t_date, job['time_start'], job['time_end'], job.get('category','default'), 4, job.get('id'))).start()
    except Exception as e:
        logging.error(f"[SCHEDULER ERROR] {e}")

try:
    scheduler = BackgroundScheduler(timezone=pytz.utc)
    scheduler.add_job(func=check_scheduled_jobs, trigger="interval", minutes=15)
    scheduler.start()
    logging.info("[SYSTEM] Scheduler OK (UTC).")
except: pass

# --- ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.getenv("WEB_PASSWORD", "admin123"):
            login_user(User(1))
            return redirect(url_for('index'))
        flash('Falsch', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    sm = StorageManager()
    cats = sm.get_categories()
    if not cats: logging.warning("[WEB] Keine Kategorien geladen.")
    return render_template('index.html', categories=cats, jobs=JobManager().jobs)

@app.route('/book', methods=['POST'])
@login_required
def book():
    d = smart_parse_date(request.form.get('date'))
    s = smart_parse_time(request.form.get('start'))
    e = smart_parse_time(request.form.get('end'))
    
    if not s or not e:
        flash('Zeit ungültig', 'danger')
        return redirect(url_for('index'))

    jm = JobManager()
    job = jm.add_job(
        "recurring" if request.form.get('frequency') != "onetime" else "onetime",
        d, s, e, request.form.get('category'), request.form.get('frequency')
    )
    
    logging.info(f"[WEB] Job erstellt: {d} {s}-{e}")
    threading.Thread(target=safe_run_booking, args=(d, s, e, job['category'], 4, job['id'])).start()
    
    flash('Gespeichert & Gestartet.', 'success')
    return redirect(url_for('index'))

@app.route('/sync')
@login_required
def sync():
    threading.Thread(target=run_sync).start()
    flash('Sync gestartet', 'info')
    return redirect(url_for('index'))

@app.route('/jobs')
@login_required
def jobs(): return render_template('jobs.html', jobs=JobManager().jobs)

@app.route('/jobs/delete/<job_id>')
@login_required
def delete_job(job_id):
    jm = JobManager()
    # FIX: Sicher filtern (nur Jobs die eine ID haben und nicht die gesuchte sind)
    jm.jobs = [j for j in jm.jobs if j.get('id') != job_id]
    jm.save_jobs()
    flash('Gelöscht.', 'warning')
    return redirect(url_for('jobs'))

@app.route('/jobs/toggle/<job_id>')
@login_required
def toggle_job(job_id):
    jm = JobManager()
    for j in jm.jobs:
        if j.get('id') == job_id: j['active'] = not j.get('active', True)
    jm.save_jobs()
    return redirect(url_for('jobs'))

@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    sm = StorageManager()
    if request.method == 'POST':
        s = sm.get_settings()
        s.append({"email": request.form.get('email'), "password": request.form.get('password'), "active": True})
        sm.save_settings(s)
        return redirect(url_for('accounts'))
    return render_template('accounts.html', accounts=sm.get_settings())

@app.route('/accounts/delete/<int:idx>')
@login_required
def delete_account(idx):
    sm = StorageManager()
    s = sm.get_settings()
    if 0 <= idx < len(s):
        s.pop(idx)
        sm.save_settings(s)
    return redirect(url_for('accounts'))

@app.route('/logs')
@login_required
def logs(): return render_template('logs.html')

@app.route('/api/logs')
@login_required
def api_logs():
    try:
        sys.stdout.flush()
        if os.path.exists("log.txt"):
            with open("log.txt", "r") as f:
                lines = [l for l in f.readlines() if "GET /api/logs" not in l and "GET /static" not in l]
                return "".join(lines[-int(request.args.get('lines', 200)):])
    except: pass
    return "Lade..."

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        if request.form.get('new_pw') == request.form.get('confirm_pw'):
            set_key(ENV_FILE, "WEB_PASSWORD", request.form.get('new_pw'))
            os.environ["WEB_PASSWORD"] = request.form.get('new_pw')
            return redirect(url_for('logout'))
    return render_template('settings.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, use_reloader=False)
