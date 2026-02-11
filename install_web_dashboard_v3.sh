#!/bin/bash

echo "[INSTALL] Starte Update auf V3 (Scheduler & Fixes)..."

# --- 1. Requirements erweitern (Scheduler) ---
cat << 'REQ' > requirements.txt
flask
flask-login
python-dotenv
playwright
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
apscheduler
REQ

# --- 2. Job Manager Upgrade (Wiederholungen) ---
# Wir überschreiben die jobs.py mit Logik für Intervalle
cat << 'PYTHON' > roombooker/jobs.py
import json
import os
import uuid
from datetime import datetime, timedelta
from .config import BASE_DIR

JOBS_FILE = BASE_DIR / "jobs.json"

class JobManager:
    def __init__(self):
        self.jobs = self.load_jobs()

    def load_jobs(self):
        if not JOBS_FILE.exists(): return []
        try:
            with open(JOBS_FILE, "r") as f: return json.load(f)
        except: return []

    def save_jobs(self):
        with open(JOBS_FILE, "w") as f: json.dump(self.jobs, f, indent=2)

    def add_job(self, job_type, target_date, time_start, time_end, category="default", frequency="onetime"):
        job = {
            "id": str(uuid.uuid4()),
            "type": job_type,           # "onetime" oder "recurring"
            "frequency": frequency,     # "daily", "weekly"
            "target_date": target_date,
            "time_start": time_start,
            "time_end": time_end,
            "category": category,
            "active": True,
            "last_booked": None
        }
        self.jobs.append(job)
        self.save_jobs()
        return job

    def get_due_jobs(self):
        """Findet Jobs, die heute/morgen fällig sind."""
        due = []
        today = datetime.now().date()
        
        for job in self.jobs:
            if not job.get("active", True): continue
            
            try:
                t_date = datetime.strptime(job["target_date"], "%d.%m.%Y").date()
                
                # Uni Bern Regel: Max 14 Tage im Voraus
                # Wir prüfen: Ist das Datum HEUTE oder in ZUKUNFT (bis +14 Tage)?
                days_diff = (t_date - today).days
                
                if 0 <= days_diff <= 14:
                    # Check ob schon gebucht für DIESES Datum
                    last = job.get("last_booked")
                    if last == job["target_date"]:
                        continue # Schon erledigt
                    
                    due.append((job, job["target_date"]))
            except: continue
            
        return due

    def mark_done(self, job_id, date_done):
        """Markiert Job als erledigt und rotiert Datum bei Wiederholung."""
        for job in self.jobs:
            if job["id"] == job_id:
                job["last_booked"] = date_done
                
                # Wiederholungs-Logik
                freq = job.get("frequency", "onetime")
                
                if freq == "weekly":
                    # Datum + 7 Tage
                    try:
                        old_date = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_date = old_date + timedelta(days=7)
                        job["target_date"] = new_date.strftime("%d.%m.%Y")
                        print(f"[JOB] Wöchentlicher Job rotiert auf: {job['target_date']}")
                    except: pass
                    
                elif freq == "daily":
                    # Datum + 1 Tag
                    try:
                        old_date = datetime.strptime(job["target_date"], "%d.%m.%Y")
                        new_date = old_date + timedelta(days=1)
                        job["target_date"] = new_date.strftime("%d.%m.%Y")
                        print(f"[JOB] Täglicher Job rotiert auf: {job['target_date']}")
                    except: pass
                
                elif freq == "onetime":
                    job["active"] = False # Deaktivieren statt löschen
                
        self.save_jobs()
PYTHON

# --- 3. Templates Update (Frequenz-Auswahl & Log Fix) ---

# index.html (Mit Frequenz-Dropdown)
cat << 'HTML' > templates/index.html
{% extends "layout.html" %}
{% block content %}
<div class="row g-4">
  <div class="col-lg-5">
    <div class="card h-100">
      <div class="card-header bg-transparent border-0 pt-4 px-4 pb-0">
        <h5 class="fw-bold mb-0"><i class="bi bi-plus-lg text-primary me-2"></i>Neue Buchung</h5>
      </div>
      <div class="card-body p-4">
        <form method="POST" action="/book">
          <div class="mb-3">
            <label class="form-label text-muted small fw-bold">DATUM</label>
            <input type="text" name="date" class="form-control" placeholder="z.B. 14.02 (Leer = Morgen)">
          </div>
          <div class="row mb-3">
            <div class="col">
              <label class="form-label text-muted small fw-bold">START</label>
              <input type="text" name="start" class="form-control" placeholder="08:00" required>
            </div>
            <div class="col">
              <label class="form-label text-muted small fw-bold">ENDE</label>
              <input type="text" name="end" class="form-control" placeholder="20:00" required>
            </div>
          </div>
          
          <div class="row mb-4">
            <div class="col-md-6">
                <label class="form-label text-muted small fw-bold">KATEGORIE</label>
                <select name="category" class="form-select">
                  {% for k, v in categories.items() %}
                  <option value="{{ k }}" {% if k == 'default' %}selected{% endif %}>{{ v.title }}</option>
                  {% else %}
                  <option value="default">Standard</option>
                  {% endfor %}
                </select>
            </div>
            <div class="col-md-6">
                <label class="form-label text-muted small fw-bold">WIEDERHOLUNG</label>
                <select name="frequency" class="form-select">
                  <option value="onetime">Einmalig</option>
                  <option value="weekly">Wöchentlich</option>
                  <option value="daily">Täglich</option>
                </select>
            </div>
          </div>
          
          <div class="d-grid gap-2">
            <button type="submit" class="btn btn-primary btn-lg">
                <i class="bi bi-rocket-takeoff me-2"></i>Speichern & Starten
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>

  <div class="col-lg-7">
    <div class="card mb-4 h-100">
      <div class="card-header bg-transparent border-0 pt-3 px-3 d-flex justify-content-between align-items-center">
        <h5 class="fw-bold mb-0"><i class="bi bi-calendar-week text-primary me-2"></i>Agenda</h5>
        <a href="/sync" class="btn btn-sm btn-outline-secondary rounded-pill px-3">
            <i class="bi bi-arrow-repeat me-1"></i> Sync
        </a>
      </div>
      <div class="card-body p-0">
        <div class="ratio ratio-4x3" style="max-height: 500px;">
            <iframe src="https://calendar.google.com/calendar/embed?height=600&wkst=2&ctz=Europe%2FZurich&showPrint=0&mode=AGENDA&title=Raumreservationen&showNav=0&src=M2FhMDI5MmJiMTAxOTU3NjA3M2VlNjUyMWJkZjdmMTJmMWM3OTU3MDNiZTRjZDAyMzMzMjE3YTgwOTM5N2I2ZUBncm91cC5jYWxlbmRhci5nb29nbGUuY29t&color=%239e69af" 
            style="border:0" frameborder="0" scrolling="no"></iframe>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="row mt-4">
    <div class="col-12">
        <div class="card border-secondary border-opacity-25">
            <div class="card-header bg-transparent border-0 d-flex justify-content-between align-items-center">
                <h6 class="mb-0 fw-bold text-muted text-uppercase"><i class="bi bi-activity me-1"></i> Live Protokoll</h6>
                <a href="/logs" class="text-decoration-none small">Vergrößern &rarr;</a>
            </div>
            <div class="card-body bg-black p-0 rounded-bottom">
                <div id="miniLog" class="p-3 font-monospace text-success small" style="height: 150px; overflow-y: hidden; opacity: 0.9; white-space: pre-wrap; font-size: 0.75rem;">
                    Lade System-Logs...
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
function updateMiniLog() {
    // Cache busting mit timestamp
    fetch('/api/logs?lines=15&t=' + Date.now())
        .then(response => response.text())
        .then(data => {
            const el = document.getElementById('miniLog');
            el.innerText = data;
            el.scrollTop = el.scrollHeight; // Immer nach unten scrollen
        });
}
setInterval(updateMiniLog, 2000); // Schnelleres Update (2s)
updateMiniLog();
</script>
{% endblock %}
HTML

# jobs.html (Spalte Frequenz anzeigen)
cat << 'HTML' > templates/jobs.html
{% extends "layout.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="fw-bold m-0">Geplante Jobs</h3>
</div>
<div class="card shadow-sm">
  <div class="table-responsive">
    <table class="table table-hover align-middle mb-0" style="background-color: transparent;">
      <thead class="text-muted small text-uppercase">
        <tr>
          <th class="ps-4">Nächstes Datum</th>
          <th>Zeit</th>
          <th>Modus</th>
          <th>Status</th>
          <th class="text-end pe-4">Aktion</th>
        </tr>
      </thead>
      <tbody class="border-top-0">
        {% for j in jobs %}
        <tr>
          <td class="ps-4 fw-bold text-white">{{ j.target_date }}</td>
          <td class="text-muted">{{ j.time_start }} - {{ j.time_end }}</td>
          <td>
            {% if j.frequency == 'weekly' %}
                <span class="badge bg-info text-dark">Wöchentlich</span>
            {% elif j.frequency == 'daily' %}
                <span class="badge bg-warning text-dark">Täglich</span>
            {% else %}
                <span class="badge bg-secondary text-light">Einmalig</span>
            {% endif %}
            <span class="badge bg-dark border border-secondary text-muted ms-1">{{ j.category }}</span>
          </td>
          <td>
            {% if j.last_booked and j.frequency == 'onetime' %}
              <span class="badge bg-success bg-opacity-10 text-success px-2 py-1 rounded-pill"><i class="bi bi-check-circle me-1"></i> Fertig</span>
            {% elif j.active %}
              <span class="badge bg-primary bg-opacity-10 text-primary px-2 py-1 rounded-pill">Aktiv</span>
            {% else %}
              <span class="badge bg-secondary bg-opacity-10 text-secondary px-2 py-1 rounded-pill">Pausiert</span>
            {% endif %}
          </td>
          <td class="text-end pe-4">
            <a href="/jobs/toggle/{{ j.id }}" class="btn btn-icon btn-sm btn-outline-secondary border-0"><i class="bi bi-pause-fill"></i></a>
            <a href="/jobs/delete/{{ j.id }}" class="btn btn-icon btn-sm btn-outline-danger border-0" onclick="return confirm('Löschen?')"><i class="bi bi-trash"></i></a>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="5" class="text-center py-5 text-muted">Keine Jobs vorhanden</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
HTML

# --- 4. Flask App (app.py) mit Scheduler & Log-Redirect ---
cat << 'PYTHON' > app.py
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
# Wir zwingen stdout/stderr in die Datei log.txt
class LoggerWriter:
    def __init__(self, filepath):
        self.terminal = sys.stdout
        self.log = open(filepath, "a", buffering=1) # Line buffering

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

# Log Redirect aktivieren
sys.stdout = LoggerWriter("log.txt")
sys.stderr = sys.stdout # Auch Fehler ins Log

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
    """Wird alle 10 Minuten ausgeführt."""
    print(f"\n[SCHEDULER] {time.strftime('%H:%M')} - Prüfe anstehende Jobs...")
    try:
        jm = JobManager()
        due_list = jm.get_due_jobs()
        if not due_list:
            print("[SCHEDULER] Keine fälligen Jobs gefunden.")
            return

        print(f"[SCHEDULER] {len(due_list)} Jobs sind fällig. Starte Verarbeitung...")
        for job, target_date in due_list:
            print(f"   -> Starte Job: {target_date} ({job['time_start']}-{job['time_end']})")
            run_booking_logic(
                target_date, 
                job['time_start'], 
                job['time_end'], 
                job['category'], 
                4, # Num accounts
                job_id=job["id"]
            )
    except Exception as e:
        print(f"[SCHEDULER ERROR] {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=check_scheduled_jobs, trigger="interval", minutes=15)
scheduler.start()

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
    
    msg = f'Job gespeichert ({freq}).'
    
    # SOFORT AUSFÜHREN (User Feedback)
    print(f"[WEB] Neuer Job erstellt. Starte sofortigen Versuch für {date_str}...")
    threading.Thread(target=run_booking_logic, args=(date_str, start_str, end_str, cat, 4, job['id'])).start()
    msg += " Buchungsvorgang im Hintergrund gestartet."

    flash(msg, 'success')
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
        # Puffer flushen vor dem Lesen sicherstellen
        sys.stdout.flush()
        if os.path.exists("log.txt"):
            with open("log.txt", "r") as f: 
                log_content = "".join(f.readlines()[-lines:])
        else: log_content = "Warte auf Log..."
    except: log_content = "Fehler."
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
    # Wichtig: use_reloader=False, sonst startet Scheduler doppelt!
    app.run(host='0.0.0.0', port=5000, use_reloader=False)
PYTHON

# --- DOCKER NEU BAUEN ---
echo "[INSTALL] Starte Docker Update..."
docker-compose down --remove-orphans
docker-compose up -d --build

echo ""
echo "=========================================================="
echo "   UPDATE V3 FERTIG"
echo "=========================================================="
echo "1. Warte 10s auf Cloudflare."
echo "2. Link holen:"
echo "   docker-compose logs tunnel | grep trycloudflare.com"
echo "=========================================================="
