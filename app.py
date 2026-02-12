import os
import sys
import threading
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# Projekt-Importe
from roombooker.config import BASE_DIR, STATUS_FILE
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from main import run_booking_logic, run_sync

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.StreamHandler(sys.stdout)])

load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Login Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id): self.id = id

@login_manager.user_loader
def load_user(user_id): return User(user_id)

# --- FIX: current_user in alle Templates injizieren ---
@app.context_processor
def inject_user():
    return dict(current_user=current_user)

@app.route('/')
@login_required
def index():
    return render_template('index.html', categories=StorageManager().get_categories() or {})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.getenv("WEB_PASSWORD", "admin123"):
            login_user(User(1))
            return redirect(url_for('index'))
        flash('Falsches Passwort', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/api/status')
@login_required
def get_status():
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r") as f:
                parts = f.read().strip().split("|", 1)
                if len(parts) == 2: return jsonify({"state": parts[0], "msg": parts[1]})
        except: pass
    return jsonify({"state": "idle", "msg": "Warte auf Auftrag..."})

@app.route('/book', methods=['POST'])
@login_required
def book():
    threading.Thread(target=run_booking_logic, args=(request.form.get('date'), request.form.get('start'), request.form.get('end'), request.form.get('category'), 4, None)).start()
    return redirect(url_for('index'))

@app.route('/sync')
@login_required
def sync():
    threading.Thread(target=run_sync).start()
    return redirect(url_for('index'))

@app.route('/jobs')
@login_required
def jobs():
    return render_template('jobs.html', jobs=JobManager().jobs)

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
def api_logs(): return "Logs siehe Terminal"

if __name__ == '__main__':
    scheduler = BackgroundScheduler(timezone=pytz.utc)
    scheduler.add_job(lambda: None, 'interval', minutes=15)
    scheduler.start()
    app.run(host='0.0.0.0', port=5000, use_reloader=False)
