import os
import sys
import threading
import logging
import time
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv, set_key
from apscheduler.schedulers.background import BackgroundScheduler

# Import Logic
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from roombooker.utils import smart_parse_date, smart_parse_time
from main import run_booking_logic, run_sync

# --- LOGGING SETUP ---
# Speichert Logs in Datei UND zeigt sie in Docker logs an
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler("log.txt"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Setup
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)
DATA_DIR = os.getenv("ROOMBOOKER_DATA_DIR", "auto_reserve_data")
ENV_FILE = ".env"

# Login Config
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id): self.id = id

@login_manager.user_loader
def load_user(user_id): return User(user_id)

# --- BACKGROUND SCHEDULER ---
def check_scheduled_jobs():
    """Wird alle 15 Minuten ausgeführt."""
    logging.info(f"[SCHEDULER] Prüfe anstehende Jobs...")
    try:
        jm = JobManager()
        due_list = jm.get_due_jobs()
        if not due_list:
            logging.info("[SCHEDULER] Keine fälligen Jobs gefunden.")
            return

        logging.info(f"[SCHEDULER] {len(due_list)} Jobs sind fällig. Starte Verarbeitung...")
        for job, target_date in due_list:
            logging.info(f"   -> Starte Job: {target_date} ({job['time_start']}-{job['time_end']})")
            run_booking_logic(
                target_date, 
                job['time_start'], 
                job['time_end'], 
                job['category'], 
                4, # Num accounts
                job_id=job["id"]
            )
    except Exception as e:
        logging.error(f"[SCHEDULER ERROR] {e}")

# FIX: Zeitzone explizit setzen, um tzlocal-Fehler zu vermeiden
try:
    scheduler = BackgroundScheduler(timezone="Europe/Zurich")
    scheduler.add_job(func=check_scheduled_jobs, trigger="interval", minutes=15)
    scheduler.start()
    logging.info("[SYSTEM] Scheduler erfolgreich gestartet.")
except Exception as e:
    logging.error(f"[SYSTEM] Konnte Scheduler nicht starten: {e}")

# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        pw = request.form.get('password')
        actual_pw = os.getenv("WEB_PASSWORD", "admin123")
        if pw == actual_pw:
            login_user(User(1))
            return redirect(url_for('index'))
        flash('Passwort falsch', 'danger')
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
    jm = JobManager()
    return render_template('index.html', categories=cats, jobs=jm.jobs)

@app.route('/book', methods=['POST'])
@login_required
def book():
    d_raw = request.form.get('date')
    s_raw = request.form.get('start')
    e_raw = request.form.get('end')
    cat = request.form.get('category')
    freq = request.form.get('frequency', 'onetime')

    date_str = smart_parse_date(d_raw)
    start_str = smart_parse_time(s_raw)
    end_str = smart_parse_time(e_raw)

    if not start_str or not end_str:
        flash('Ungültige Zeitangabe!', 'danger')
        return redirect(url_for('index'))

    # Job erstellen
    jm = JobManager()
    job = jm.add_job("recurring" if freq != "onetime" else "onetime", 
                     target_date=date_str, 
                     time_start=start_str, 
                     time_end=end_str, 
                     category=cat,
                     frequency=freq)
    
    # Logging für sofortiges Feedback
    logging.info(f"[WEB] Neuer Job ({freq}) erstellt: {date_str} {start_str}-{end_str}")
    
    # SOFORT AUSFÜHREN
    flash(f'Job gespeichert. Starte sofortigen Buchungsversuch...', 'success')
    threading.Thread(target=run_booking_logic, args=(date_str, start_str, end_str, cat, 4, job['id'])).start()
    
    return redirect(url_for('index'))

@app.route('/sync')
@login_required
def sync():
    threading.Thread(target=run_sync).start()
    flash('Sync gestartet...', 'info')
    return redirect(url_for('index'))

@app.route('/jobs')
@login_required
def jobs():
    return render_template('jobs.html', jobs=JobManager().jobs)

@app.route('/jobs/delete/<job_id>')
@login_required
def delete_job(job_id):
    jm = JobManager()
    jm.jobs = [j for j in jm.jobs if j['id'] != job_id]
    jm.save_jobs()
    flash('Job gelöscht.', 'warning')
    return redirect(url_for('jobs'))

@app.route('/jobs/toggle/<job_id>')
@login_required
def toggle_job(job_id):
    jm = JobManager()
    for j in jm.jobs:
        if j['id'] == job_id:
            j['active'] = not j.get('active', True)
    jm.save_jobs()
    return redirect(url_for('jobs'))

@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    sm = StorageManager()
    if request.method == 'POST':
        email = request.form.get('email')
        pw = request.form.get('password')
        settings = sm.get_settings()
        settings.append({"email": email, "password": pw, "active": True})
        sm.save_settings(settings)
        flash('Account gespeichert.', 'success')
        return redirect(url_for('accounts'))
    return render_template('accounts.html', accounts=sm.get_settings())

@app.route('/accounts/delete/<int:idx>')
@login_required
def delete_account(idx):
    sm = StorageManager()
    settings = sm.get_settings()
    if 0 <= idx < len(settings):
        settings.pop(idx)
        sm.save_settings(settings)
        flash('Account entfernt.', 'warning')
    return redirect(url_for('accounts'))

@app.route('/logs')
@login_required
def logs():
    return render_template('logs.html')

@app.route('/api/logs')
@login_required
def api_logs():
    lines = request.args.get('lines', default=200, type=int)
    log_content = ""
    try:
        # Sicherstellen, dass alles auf die Platte geschrieben wurde
        sys.stdout.flush()
        if os.path.exists("log.txt"):
            with open("log.txt", "r") as f: 
                log_content = "".join(f.readlines()[-lines:])
        else: log_content = "Warte auf Log..."
    except: log_content = "Fehler beim Lesen."
    return log_content

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        new = request.form.get('new_pw')
        conf = request.form.get('confirm_pw')
        if new == conf and new:
            set_key(ENV_FILE, "WEB_PASSWORD", new)
            os.environ["WEB_PASSWORD"] = new
            flash('Passwort geändert.', 'success')
            return redirect(url_for('logout'))
        flash('Fehler beim Ändern.', 'danger')
    return render_template('settings.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, use_reloader=False)
