#!/bin/bash

# Ordnerstruktur
mkdir -p templates static routes
echo "[INSTALL] Ordnerstruktur erstellt."

# Requirements erweitern
cat << 'REQ' > requirements.txt
flask
flask-login
python-dotenv
playwright
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
REQ
echo "[INSTALL] requirements.txt aktualisiert."

# Docker Compose (mit Cloudflare Tunnel)
cat << 'DOCKER' > docker-compose.yml
services:
  app:
    build: .
    container_name: roombooker_app
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./auto_reserve_data:/root/auto_reserve_data
      - .:/app
    environment:
      - ROOMBOOKER_DATA_DIR=/root/auto_reserve_data
      - PYTHONUNBUFFERED=1
    command: python3 app.py

  tunnel:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --url http://app:5000
    depends_on:
      - app
DOCKER
echo "[INSTALL] docker-compose.yml aktualisiert."

# --- HTML TEMPLATES (Bootstrap 5.3 Dark Mode) ---

# layout.html
cat << 'HTML' > templates/layout.html
<!doctype html>
<html lang="de" data-bs-theme="dark">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RoomBooker Pro</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
      body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
      .card { background-color: #1e1e1e; border: 1px solid #333; margin-bottom: 1rem; }
      .navbar { background-color: #1f1f1f !important; border-bottom: 1px solid #333; }
      .btn-primary { background-color: #bb86fc; border-color: #bb86fc; color: #000; font-weight: 600; }
      .btn-primary:hover { background-color: #9965f4; border-color: #9965f4; }
      .form-control, .form-select { background-color: #2d2d2d; border-color: #444; color: #fff; }
      .form-control:focus, .form-select:focus { background-color: #333; color: #fff; border-color: #bb86fc; box-shadow: 0 0 0 0.25rem rgba(187, 134, 252, 0.25); }
      /* Mobile Optimierungen */
      @media (max-width: 768px) {
        .container { padding-left: 10px; padding-right: 10px; }
        .card-body { padding: 1rem; }
        h5 { font-size: 1.1rem; }
      }
    </style>
  </head>
  <body>
    {% if current_user.is_authenticated %}
    <nav class="navbar navbar-expand-lg navbar-dark mb-3">
      <div class="container-fluid">
        <a class="navbar-brand fw-bold" href="/"><i class="bi bi-calendar-check-fill text-primary"></i> RoomBooker</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto">
            <li class="nav-item"><a class="nav-link" href="/"><i class="bi bi-speedometer2"></i> Dashboard</a></li>
            <li class="nav-item"><a class="nav-link" href="/jobs"><i class="bi bi-list-task"></i> Jobs</a></li>
            <li class="nav-item"><a class="nav-link" href="/accounts"><i class="bi bi-people"></i> Accounts</a></li>
            <li class="nav-item"><a class="nav-link" href="/logs"><i class="bi bi-terminal"></i> Logs</a></li>
            <li class="nav-item"><a class="nav-link" href="/settings"><i class="bi bi-gear"></i> Settings</a></li>
            <li class="nav-item"><a class="nav-link text-danger" href="/logout"><i class="bi bi-box-arrow-right"></i> Logout</a></li>
          </ul>
        </div>
      </div>
    </nav>
    {% endif %}

    <div class="container">
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          {% for category, message in messages %}
            <div class="alert alert-{{ category }} alert-dismissible fade show shadow-sm" role="alert">
              {{ message }}
              <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}
      
      {% block content %}{% endblock %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
HTML

# login.html
cat << 'HTML' > templates/login.html
{% extends "layout.html" %}
{% block content %}
<div class="row justify-content-center" style="min-height: 80vh; align-items: center;">
  <div class="col-md-6 col-lg-4">
    <div class="card shadow-lg border-0">
      <div class="card-body p-5">
        <div class="text-center mb-4">
          <i class="bi bi-shield-lock-fill text-primary" style="font-size: 3rem;"></i>
          <h3 class="mt-3">Login</h3>
        </div>
        <form method="POST">
          <div class="mb-4">
            <input type="password" name="password" class="form-control form-control-lg text-center" placeholder="Passwort eingeben" autofocus required>
          </div>
          <button type="submit" class="btn btn-primary w-100 btn-lg">Entsperren</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
HTML

# index.html
cat << 'HTML' > templates/index.html
{% extends "layout.html" %}
{% block content %}
<div class="row g-3">
  <div class="col-lg-5">
    <div class="card h-100 shadow-sm">
      <div class="card-header bg-transparent border-secondary py-3">
        <h5 class="mb-0 fw-bold"><i class="bi bi-plus-circle text-success"></i> Neue Buchung</h5>
      </div>
      <div class="card-body">
        <form method="POST" action="/book">
          <div class="mb-3">
            <label class="form-label text-muted small text-uppercase fw-bold">Datum</label>
            <input type="text" name="date" class="form-control form-control-lg" placeholder="z.B. 14.02 (Leer = Morgen)">
          </div>
          <div class="row mb-3">
            <div class="col">
              <label class="form-label text-muted small text-uppercase fw-bold">Start</label>
              <input type="text" name="start" class="form-control form-control-lg" placeholder="08:00" required>
            </div>
            <div class="col">
              <label class="form-label text-muted small text-uppercase fw-bold">Ende</label>
              <input type="text" name="end" class="form-control form-control-lg" placeholder="20:00" required>
            </div>
          </div>
          <div class="mb-3">
            <label class="form-label text-muted small text-uppercase fw-bold">Kategorie</label>
            <select name="category" class="form-select form-select-lg">
              {% for k, v in categories.items() %}
              <option value="{{ k }}" {% if k == 'default' %}selected{% endif %}>{{ v.title }}</option>
              {% endfor %}
            </select>
          </div>
          <div class="form-check form-switch mb-4">
            <input class="form-check-input" type="checkbox" name="is_job" id="isJob">
            <label class="form-check-label" for="isJob">Als wiederkehrenden Job speichern</label>
          </div>
          <button type="submit" class="btn btn-primary w-100 btn-lg"><i class="bi bi-rocket-takeoff"></i> Buchen Starten</button>
        </form>
      </div>
    </div>
  </div>

  <div class="col-lg-7">
    <div class="card mb-3 shadow-sm">
      <div class="card-header bg-transparent border-secondary d-flex justify-content-between align-items-center py-2">
        <h5 class="mb-0 fw-bold"><i class="bi bi-calendar3 text-info"></i> Übersicht</h5>
        <a href="/sync" class="btn btn-sm btn-outline-info"><i class="bi bi-arrow-repeat"></i> Sync</a>
      </div>
      <div class="card-body p-0">
        <div class="ratio ratio-16x9">
            <iframe src="https://calendar.google.com/calendar/embed?height=600&wkst=1&ctz=Europe%2FZurich&showPrint=0&src=bGVhbmRyby5hZXNjaGJhY2hlcjc3QGdtYWlsLmNvbQ&src=M2FhMDI5MmJiMTAxOTU3NjA3M2VlNjUyMWJkZjdmMTJmMWM3OTU3MDNiZTRjZDAyMzMzMjE3YTgwOTM5N2I2ZUBncm91cC5jYWxlbmRhci5nb29nbGUuY29t&src=YjU4YzBkMGMyY2M1MTVkYjZiMWY0OTM5Njk3MzY0NDg4YTJjZTM5NDQ0ZmI0NmJiNjgzNWMyZWE1YzBhYTk5OEBncm91cC5jYWxlbmRhci5nb29nbGUuY29t&src=ZmFtaWx5MDYzNjI3MjQyMzQyMjAzNDY1NDNAZ3JvdXAuY2FsZW5kYXIuZ29vZ2xlLmNvbQ&src=NWQ5ZmFkMGVjOTY3Mzg5M2UyMzgzNDI2NWMwYWIxMmJmM2M5ODk2NzkwMGU2ZTVlYTFhZDliZTgxNzFjYmI4ZUBncm91cC5jYWxlbmRhci5nb29nbGUuY29t&color=%23795548&color=%239e69af&color=%23ef6c00&color=%233f51b5&color=%237986cb" style="border:0" frameborder="0" scrolling="no"></iframe>
        </div>
      </div>
    </div>

    <div class="card shadow-sm">
      <div class="card-header bg-transparent border-secondary py-2">
        <h5 class="mb-0 fw-bold text-muted small text-uppercase">Nächste Jobs</h5>
      </div>
      <div class="list-group list-group-flush">
        {% for j in jobs[:3] %}
        <div class="list-group-item bg-transparent text-light d-flex justify-content-between align-items-center">
            <div>
                <i class="bi bi-clock-history text-warning me-2"></i>
                <strong>{{ j.target_date }}</strong> <span class="text-muted">| {{ j.time_start }}-{{ j.time_end }}</span>
            </div>
            {% if j.active %}<span class="badge bg-success rounded-pill">Aktiv</span>{% else %}<span class="badge bg-secondary rounded-pill">Pause</span>{% endif %}
        </div>
        {% else %}
        <div class="list-group-item bg-transparent text-muted text-center py-3">Keine Jobs geplant</div>
        {% endfor %}
      </div>
      {% if jobs|length > 3 %}
      <div class="card-footer bg-transparent border-secondary text-center">
        <a href="/jobs" class="text-decoration-none text-info small">Alle Jobs anzeigen</a>
      </div>
      {% endif %}
    </div>
  </div>
</div>
{% endblock %}
HTML

# jobs.html
cat << 'HTML' > templates/jobs.html
{% extends "layout.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h3 class="fw-bold m-0"><i class="bi bi-list-task"></i> Job Verwaltung</h3>
</div>
<div class="card shadow-sm">
  <div class="table-responsive">
    <table class="table table-dark table-hover align-middle mb-0">
      <thead class="table-light text-dark">
        <tr>
          <th>Datum</th>
          <th>Zeit</th>
          <th>Kategorie</th>
          <th>Status</th>
          <th class="text-end">Aktionen</th>
        </tr>
      </thead>
      <tbody>
        {% for j in jobs %}
        <tr>
          <td class="fw-bold">{{ j.target_date }}</td>
          <td>{{ j.time_start }} - {{ j.time_end }}</td>
          <td><span class="badge bg-secondary">{{ j.category }}</span></td>
          <td>
            {% if j.last_booked %}
              <span class="badge bg-success"><i class="bi bi-check-circle"></i> Erledigt</span>
            {% elif j.active %}
              <span class="badge bg-primary">Aktiv</span>
            {% else %}
              <span class="badge bg-secondary">Pausiert</span>
            {% endif %}
          </td>
          <td class="text-end">
            <a href="/jobs/toggle/{{ j.id }}" class="btn btn-sm btn-outline-light me-1"><i class="bi bi-pause-fill"></i></a>
            <a href="/jobs/delete/{{ j.id }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Löschen?')"><i class="bi bi-trash"></i></a>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="5" class="text-center py-4 text-muted">Keine Jobs vorhanden</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
HTML

# accounts.html
cat << 'HTML' > templates/accounts.html
{% extends "layout.html" %}
{% block content %}
<div class="row g-4">
  <div class="col-md-7">
    <div class="card shadow-sm h-100">
      <div class="card-header bg-transparent border-secondary">
        <h5 class="mb-0 fw-bold"><i class="bi bi-person-badge"></i> Gespeicherte Accounts</h5>
      </div>
      <div class="card-body p-0">
        <ul class="list-group list-group-flush">
          {% for acc in accounts %}
          <li class="list-group-item bg-transparent text-light d-flex justify-content-between align-items-center py-3">
            <div class="d-flex align-items-center">
                <div class="bg-primary rounded-circle d-flex align-items-center justify-content-center me-3" style="width:40px; height:40px;">
                    <i class="bi bi-person-fill h5 m-0 text-dark"></i>
                </div>
                <div>
                    <div class="fw-bold">{{ acc.email }}</div>
                    <div class="small text-muted">Passwort: ••••••••</div>
                </div>
            </div>
            <a href="/accounts/delete/{{ loop.index0 }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Account entfernen?')"><i class="bi bi-trash"></i></a>
          </li>
          {% else %}
          <li class="list-group-item bg-transparent text-muted text-center py-4">Keine Accounts hinterlegt.</li>
          {% endfor %}
        </ul>
      </div>
    </div>
  </div>
  <div class="col-md-5">
    <div class="card shadow-sm border-success h-100">
      <div class="card-header bg-success text-dark fw-bold">
        <i class="bi bi-person-plus-fill"></i> Account hinzufügen
      </div>
      <div class="card-body">
        <form method="POST">
          <div class="mb-3">
            <label class="form-label">E-Mail (Edu-ID)</label>
            <input type="email" name="email" class="form-control" required>
          </div>
          <div class="mb-3">
            <label class="form-label">Passwort</label>
            <input type="password" name="password" class="form-control" required>
          </div>
          <button type="submit" class="btn btn-success w-100">Speichern</button>
        </form>
        <div class="mt-3 text-muted small">
            <i class="bi bi-shield-check"></i> Daten werden nur lokal auf diesem Server gespeichert.
        </div>
      </div>
    </div>
  </div>
</div>
{% endblock %}
HTML

# settings.html
cat << 'HTML' > templates/settings.html
{% extends "layout.html" %}
{% block content %}
<div class="row justify-content-center mt-4">
  <div class="col-md-6 col-lg-5">
    <div class="card border-warning shadow-lg">
      <div class="card-header bg-warning text-dark fw-bold text-center py-3">
        <i class="bi bi-key-fill"></i> Web-Passwort ändern
      </div>
      <div class="card-body p-4">
        <form method="POST">
          <div class="form-floating mb-3">
            <input type="password" name="current_pw" class="form-control" id="curr" placeholder="Aktuell" required>
            <label for="curr" class="text-dark">Aktuelles Passwort</label>
          </div>
          <hr class="border-secondary my-4">
          <div class="form-floating mb-2">
            <input type="password" name="new_pw" class="form-control" id="new" placeholder="Neu" required>
            <label for="new" class="text-dark">Neues Passwort</label>
          </div>
          <div class="form-floating mb-4">
            <input type="password" name="confirm_pw" class="form-control" id="conf" placeholder="Wdh" required>
            <label for="conf" class="text-dark">Wiederholen</label>
          </div>
          <button type="submit" class="btn btn-warning w-100 btn-lg fw-bold text-dark">Speichern & Logout</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
HTML

# logs.html
cat << 'HTML' > templates/logs.html
{% extends "layout.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h3 class="fw-bold m-0"><i class="bi bi-terminal"></i> System Logs</h3>
    <a href="/logs" class="btn btn-sm btn-outline-light"><i class="bi bi-arrow-clockwise"></i> Refresh</a>
</div>
<div class="card bg-black border-secondary shadow-sm">
  <div class="card-body p-0">
    <pre class="m-0 p-3 text-success font-monospace" style="height: 75vh; overflow-y: scroll; font-size: 0.85rem; line-height: 1.4;">{{ logs }}</pre>
  </div>
</div>
<script>
  const pre = document.querySelector('pre');
  pre.scrollTop = pre.scrollHeight;
</script>
{% endblock %}
HTML

echo "[INSTALL] Templates erstellt."

# --- FLASK APP ---
cat << 'PYTHON' > app.py
import os
import threading
import logging
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv, set_key

# Import Core Logic
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from roombooker.utils import smart_parse_date, smart_parse_time
# Import main functions (assuming main.py is in the same dir)
from main import run_booking_logic, run_sync

# Setup
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)

DATA_DIR = os.getenv("ROOMBOOKER_DATA_DIR", "auto_reserve_data")
ENV_FILE = ".env"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id): self.id = id

@login_manager.user_loader
def load_user(user_id): return User(user_id)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        pw = request.form.get('password')
        actual_pw = os.getenv("WEB_PASSWORD", "admin123")
        if pw == actual_pw:
            login_user(User(1))
            return redirect(url_for('index'))
        flash('Falsches Passwort!', 'danger')
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
    is_job = request.form.get('is_job')

    date_str = smart_parse_date(d_raw)
    start_str = smart_parse_time(s_raw)
    end_str = smart_parse_time(e_raw)

    if not start_str or not end_str:
        flash('Ungültige Zeitangabe!', 'danger')
        return redirect(url_for('index'))

    if is_job:
        JobManager().add_job("onetime", target_date=date_str, time_start=start_str, time_end=end_str, category=cat)
        flash(f'Job für {date_str} gespeichert.', 'success')
    else:
        flash(f'Buchung für {date_str} gestartet! Check Logs.', 'info')
        threading.Thread(target=run_booking_logic, args=(date_str, start_str, end_str, cat, 4)).start()

    return redirect(url_for('index'))

@app.route('/sync')
@login_required
def sync():
    threading.Thread(target=run_sync).start()
    flash('Kalender Sync gestartet...', 'info')
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
        flash('Account hinzugefügt.', 'success')
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
        flash('Account gelöscht.', 'warning')
    return redirect(url_for('accounts'))

@app.route('/logs')
@login_required
def logs():
    log_content = ""
    try:
        # Versuche verschiedene Log-Quellen
        if os.path.exists("log.txt"):
            with open("log.txt", "r") as f: log_content = "".join(f.readlines()[-300:])
        else:
            log_content = "log.txt nicht gefunden. (Läuft der Container?)"
    except: log_content = "Fehler beim Lesen des Logs."
    return render_template('logs.html', logs=log_content)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        curr = request.form.get('current_pw')
        new = request.form.get('new_pw')
        conf = request.form.get('confirm_pw')
        
        actual = os.getenv("WEB_PASSWORD", "admin123")
        
        if curr != actual:
            flash('Aktuelles Passwort falsch!', 'danger')
        elif new != conf:
            flash('Passwörter stimmen nicht überein!', 'danger')
        else:
            set_key(ENV_FILE, "WEB_PASSWORD", new)
            os.environ["WEB_PASSWORD"] = new
            flash('Passwort erfolgreich geändert! Bitte neu einloggen.', 'success')
            return redirect(url_for('logout'))
            
    return render_template('settings.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
PYTHON
echo "[INSTALL] Flask App (app.py) erstellt."

# .env Initialisierung
if [ ! -f .env ]; then
    echo "WEB_PASSWORD=admin123" > .env
    echo "ROOMBOOKER_DATA_DIR=auto_reserve_data" >> .env
    echo "[INSTALL] .env mit Standard-Passwort 'admin123' erstellt."
fi

# DOCKER RESTART
echo "[INSTALL] Starte Docker..."
docker-compose down --remove-orphans
docker-compose up -d --build

echo ""
echo "=========================================================="
echo "   INSTALLATION ERFOLGREICH ABGESCHLOSSEN "
echo "=========================================================="
echo "1. Warte ca. 10 Sekunden, bis der Tunnel steht."
echo "2. Um deine URL zu sehen, tippe:"
echo "   docker-compose logs tunnel | grep trycloudflare.com"
echo ""
echo "Das Standard-Passwort ist: admin123"
echo "=========================================================="
