import os, sys, threading, logging, time
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv, set_key
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from roombooker.utils import smart_parse_date, smart_parse_time
from main import run_booking_logic, run_sync

DATA_DIR = "/root/auto_reserve_data"
os.environ["ROOMBOOKER_DATA_DIR"] = DATA_DIR 
STATUS_FILE = os.path.join(DATA_DIR, "web_status.txt")
ENV_FILE = ".env"

# Logger Konfiguration
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s', handlers=[logging.FileHandler("log.txt"), logging.StreamHandler(sys.stdout)])

# Filter für saubere Logs
class CleanLogFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not any(x in msg for x in ["GET /api/", "GET /static/", "GET /logs"])
for h in logging.getLogger().handlers: h.addFilter(CleanLogFilter())
logging.getLogger('werkzeug').addFilter(CleanLogFilter())

load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
login_manager = LoginManager(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id): self.id = id
@login_manager.user_loader
def load_user(user_id): return User(user_id)

# Scheduler
def check_scheduled_jobs():
    try:
        jm = JobManager()
        due = jm.get_due_jobs()
        for job, t_date in due:
            threading.Thread(target=run_booking_logic, args=(t_date, job['time_start'], job['time_end'], job.get('category','default'), 4, job.get('id'))).start()
    except: pass

try:
    scheduler = BackgroundScheduler(timezone=pytz.utc)
    scheduler.add_job(func=check_scheduled_jobs, trigger="interval", minutes=15)
    scheduler.start()
except: pass

# --- ROUTEN ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.getenv("WEB_PASSWORD", "admin123"):
            login_user(User(1)); return redirect(url_for('index'))
        flash('Passwort falsch', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html', categories=StorageManager().get_categories())

@app.route('/api/status')
@login_required
def get_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            c = f.read().strip().split("|", 1)
            if len(c) == 2: return jsonify({"state": c[0], "msg": c[1]})
    return jsonify({"state": "idle", "msg": "System bereit."})

@app.route('/book', methods=['POST'])
@login_required
def book():
    d = smart_parse_date(request.form.get('date'))
    s = smart_parse_time(request.form.get('start'))
    e = smart_parse_time(request.form.get('end'))
    cat = request.form.get('category')
    jm = JobManager()
    job = jm.add_job("onetime", d, s, e, cat, request.form.get('frequency'))
    # Status sofort setzen
    with open(STATUS_FILE, "w") as f: f.write(f"info|Starte Job {d}...")
    threading.Thread(target=run_booking_logic, args=(d, s, e, cat, 4, job['id'])).start()
    return redirect(url_for('index'))

@app.route('/sync')
@login_required
def sync():
    threading.Thread(target=run_sync).start()
    return redirect(url_for('index'))

@app.route('/jobs')
@login_required
def jobs(): return render_template('jobs.html', jobs=JobManager().jobs)

@app.route('/jobs/delete/<job_id>')
@login_required
def delete_job(job_id):
    jm = JobManager()
    jm.jobs = [j for j in jm.jobs if j.get('id') != job_id]
    jm.save_jobs()
    return redirect(url_for('jobs'))

@app.route('/jobs/toggle/<job_id>')
@login_required
def toggle_job(job_id):
    jm = JobManager()
    for j in jm.jobs:
        if j.get('id') == job_id: j['active'] = not j.get('active', True)
    jm.save_jobs()
    return redirect(url_for('jobs'))

# --- WIEDERHERGESTELLTE ROUTEN ---

@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    sm = StorageManager()
    if request.method == 'POST':
        s = sm.get_settings()
        s.append({"email": request.form.get('email'), "password": request.form.get('password'), "active": True})
        sm.save_settings(s)
        flash('Account gespeichert.', 'success')
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
        flash('Account gelöscht.', 'warning')
    return redirect(url_for('accounts'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        if request.form.get('new_pw') == request.form.get('confirm_pw'):
            set_key(ENV_FILE, "WEB_PASSWORD", request.form.get('new_pw'))
            os.environ["WEB_PASSWORD"] = request.form.get('new_pw')
            flash('Passwort geändert.', 'success')
            return redirect(url_for('logout'))
        else:
            flash('Passwörter stimmen nicht überein.', 'danger')
    return render_template('settings.html')

@app.route('/logs')
@login_required
def logs(): return render_template('logs.html')

@app.route('/api/logs')
@login_required
def api_logs():
    try:
        if os.path.exists("log.txt"):
            with open("log.txt", "r") as f:
                # Filtert API Calls raus, zeigt aber Logik-Events
                lines = [l for l in f.readlines() if "GET /api/" not in l]
                return "".join(lines[-200:])
    except: pass
    return "Lade..."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
