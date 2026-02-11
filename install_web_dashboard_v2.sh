#!/bin/bash

# --- 1. Aufräumen ---
echo "[INSTALL] Bereinige alte Installation..."
rm -rf templates static

# --- 2. Struktur anlegen ---
mkdir -p templates static/css static/js routes
echo "[INSTALL] Ordnerstruktur erstellt."

# --- 3. Requirements (Keine Änderung nötig, aber zur Sicherheit) ---
cat << 'REQ' > requirements.txt
flask
flask-login
python-dotenv
playwright
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
REQ

# --- 4. CSS (Modern & Polished) ---
cat << 'CSS' > static/css/style.css
:root {
    --bg-body: #0f172a;
    --bg-card: #1e293b;
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
    --accent: #6366f1; /* Indigo */
    --accent-hover: #4f46e5;
    --border: #334155;
}

body {
    background-color: var(--bg-body);
    color: var(--text-main);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
}

.card {
    background-color: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}

.navbar {
    background-color: rgba(30, 41, 59, 0.8) !important;
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
}

.form-control, .form-select {
    background-color: #0f172a;
    border: 1px solid var(--border);
    color: var(--text-main);
    border-radius: 8px;
    padding: 0.75rem 1rem;
}

.form-control:focus, .form-select:focus {
    background-color: #0f172a;
    border-color: var(--accent);
    box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
    color: var(--text-main);
}

.btn-primary {
    background-color: var(--accent);
    border: none;
    border-radius: 8px;
    padding: 0.75rem 1.5rem;
    font-weight: 600;
    transition: all 0.2s ease;
}

.btn-primary:hover {
    background-color: var(--accent-hover);
    transform: translateY(-1px);
}

/* Loading Overlay */
#loadingOverlay {
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(15, 23, 42, 0.9);
    z-index: 9999;
    display: none;
    justify-content: center;
    align-items: center;
    flex-direction: column;
}

/* Scrollbar für Logs */
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-track { background: var(--bg-body); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
CSS

# --- 5. HTML Templates ---

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
    <link rel="stylesheet" href="/static/css/style.css">
  </head>
  <body>
    <div id="loadingOverlay">
        <div class="spinner-border text-primary" style="width: 3rem; height: 3rem;" role="status"></div>
        <h5 class="mt-3 text-light">Verarbeite Anfrage...</h5>
    </div>

    {% if current_user.is_authenticated %}
    <nav class="navbar navbar-expand-lg navbar-dark mb-4 sticky-top">
      <div class="container">
        <a class="navbar-brand fw-bold" href="/"><i class="bi bi-calendar-check-fill text-primary"></i> RoomBooker</a>
        <button class="navbar-toggler border-0" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto">
            <li class="nav-item"><a class="nav-link" href="/"><i class="bi bi-grid"></i> Dashboard</a></li>
            <li class="nav-item"><a class="nav-link" href="/jobs"><i class="bi bi-clock-history"></i> Jobs</a></li>
            <li class="nav-item"><a class="nav-link" href="/accounts"><i class="bi bi-people"></i> Accounts</a></li>
            <li class="nav-item"><a class="nav-link" href="/logs"><i class="bi bi-terminal"></i> Logs</a></li>
            <li class="nav-item dropdown">
                <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown"><i class="bi bi-gear"></i></a>
                <ul class="dropdown-menu dropdown-menu-end border-0 shadow">
                    <li><a class="dropdown-item" href="/settings">Passwort ändern</a></li>
                    <li><hr class="dropdown-divider"></li>
                    <li><a class="dropdown-item text-danger" href="/logout">Logout</a></li>
                </ul>
            </li>
          </ul>
        </div>
      </div>
    </nav>
    {% endif %}

    <div class="container pb-5">
      <div class="toast-container position-fixed top-0 end-0 p-3">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="toast align-items-center text-bg-{{ category }} border-0 show" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                  <div class="toast-body">{{ message }}</div>
                  <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
      </div>
      
      {% block content %}{% endblock %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Loading Overlay aktivieren bei Form Submit
        document.querySelectorAll('form').forEach(form => {
            form.addEventListener('submit', function() {
                // Nur zeigen wenn es kein "Background" Job ist (z.B. nicht beim Filter)
                if(!this.classList.contains('no-loading')) {
                    document.getElementById('loadingOverlay').style.display = 'flex';
                }
            });
        });
    </script>
    {% block scripts %}{% endblock %}
  </body>
</html>
HTML

# login.html
cat << 'HTML' > templates/login.html
{% extends "layout.html" %}
{% block content %}
<div class="d-flex justify-content-center align-items-center" style="min-height: 80vh;">
  <div class="card shadow-lg border-0" style="width: 100%; max-width: 400px;">
    <div class="card-body p-5">
      <div class="text-center mb-5">
        <div class="bg-primary bg-opacity-10 rounded-circle d-inline-flex p-3 mb-3">
            <i class="bi bi-shield-lock-fill text-primary" style="font-size: 2rem;"></i>
        </div>
        <h4 class="fw-bold">Willkommen zurück</h4>
        <p class="text-muted small">Bitte authentifizieren Sie sich.</p>
      </div>
      <form method="POST">
        <div class="mb-4">
          <input type="password" name="password" class="form-control form-control-lg text-center" placeholder="••••••••" autofocus required>
        </div>
        <button type="submit" class="btn btn-primary w-100 btn-lg">Login</button>
      </form>
    </div>
  </div>
</div>
{% endblock %}
HTML

# index.html
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
          <div class="mb-4">
            <label class="form-label text-muted small fw-bold">KATEGORIE</label>
            <select name="category" class="form-select">
              {% for k, v in categories.items() %}
              <option value="{{ k }}" {% if k == 'default' %}selected{% endif %}>
                {{ v.title }} ({{ v.desc }})
              </option>
              {% else %}
              <option value="default">Standard (Fallback)</option>
              {% endfor %}
            </select>
            {% if not categories %}
            <div class="form-text text-danger"><i class="bi bi-exclamation-triangle"></i> Keine Kategorien geladen!</div>
            {% endif %}
          </div>
          
          <div class="d-grid gap-2">
            <button type="submit" class="btn btn-primary btn-lg">
                <i class="bi bi-lightning-charge-fill me-2"></i>Jetzt Buchen
            </button>
            <div class="form-check form-switch d-flex justify-content-center mt-2">
                <input class="form-check-input me-2" type="checkbox" name="is_job" id="isJob">
                <label class="form-check-label text-muted small" for="isJob">Als wiederkehrenden Job speichern</label>
            </div>
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
        <div class="card">
            <div class="card-header bg-transparent border-0 d-flex justify-content-between align-items-center">
                <h6 class="mb-0 fw-bold text-muted text-uppercase">Live Aktivität</h6>
                <a href="/logs" class="text-decoration-none small">Alle Logs &rarr;</a>
            </div>
            <div class="card-body bg-black p-0 rounded-bottom">
                <div id="miniLog" class="p-3 font-monospace text-success small" style="height: 150px; overflow-y: hidden; opacity: 0.8;">
                    Lade Logs...
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
function updateMiniLog() {
    fetch('/api/logs?lines=10')
        .then(response => response.text())
        .then(data => {
            document.getElementById('miniLog').innerText = data;
        });
}
setInterval(updateMiniLog, 3000); // Alle 3s aktualisieren
updateMiniLog();
</script>
{% endblock %}
HTML

# jobs.html
cat << 'HTML' > templates/jobs.html
{% extends "layout.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h3 class="fw-bold m-0">Job Verwaltung</h3>
</div>
<div class="card">
  <div class="table-responsive">
    <table class="table table-hover align-middle mb-0" style="background-color: transparent;">
      <thead class="text-muted small text-uppercase">
        <tr>
          <th class="ps-4">Datum</th>
          <th>Zeit</th>
          <th>Kategorie</th>
          <th>Status</th>
          <th class="text-end pe-4">Aktion</th>
        </tr>
      </thead>
      <tbody class="border-top-0">
        {% for j in jobs %}
        <tr>
          <td class="ps-4 fw-bold text-white">{{ j.target_date }}</td>
          <td class="text-muted">{{ j.time_start }} - {{ j.time_end }}</td>
          <td><span class="badge bg-dark border border-secondary text-light">{{ j.category }}</span></td>
          <td>
            {% if j.last_booked %}
              <span class="badge bg-success bg-opacity-10 text-success px-3 py-2 rounded-pill"><i class="bi bi-check-circle me-1"></i> Erledigt</span>
            {% elif j.active %}
              <span class="badge bg-primary bg-opacity-10 text-primary px-3 py-2 rounded-pill">Aktiv</span>
            {% else %}
              <span class="badge bg-secondary bg-opacity-10 text-secondary px-3 py-2 rounded-pill">Pausiert</span>
            {% endif %}
          </td>
          <td class="text-end pe-4">
            <a href="/jobs/toggle/{{ j.id }}" class="btn btn-icon btn-sm btn-outline-secondary border-0"><i class="bi bi-pause-fill"></i></a>
            <a href="/jobs/delete/{{ j.id }}" class="btn btn-icon btn-sm btn-outline-danger border-0" onclick="return confirm('Löschen?')"><i class="bi bi-trash"></i></a>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="5" class="text-center py-5 text-muted">Keine Jobs geplant</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
HTML

# logs.html (Auto-Refresh)
cat << 'HTML' > templates/logs.html
{% extends "layout.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h3 class="fw-bold m-0">System Logs</h3>
    <div class="text-muted small"><span id="statusIndicator" class="text-success">●</span> Live</div>
</div>
<div class="card bg-black border-secondary shadow-sm">
  <div class="card-body p-0">
    <pre id="logContainer" class="m-0 p-3 text-success font-monospace" style="height: 75vh; overflow-y: scroll; font-size: 0.85rem; line-height: 1.5; white-space: pre-wrap;">Lade...</pre>
  </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    const logContainer = document.getElementById('logContainer');
    let autoScroll = true;

    // Wenn User scrollt, Auto-Scroll deaktivieren
    logContainer.addEventListener('scroll', () => {
        if (logContainer.scrollTop + logContainer.clientHeight >= logContainer.scrollHeight - 20) {
            autoScroll = true;
        } else {
            autoScroll = false;
        }
    });

    function fetchLogs() {
        fetch('/api/logs?lines=500')
            .then(res => res.text())
            .then(data => {
                logContainer.innerText = data;
                if(autoScroll) {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }
                document.getElementById('statusIndicator').className = "text-success";
            })
            .catch(err => {
                document.getElementById('statusIndicator').className = "text-danger";
            });
    }
    
    // Alle 2 Sekunden Log holen
    setInterval(fetchLogs, 2000);
    fetchLogs();
</script>
{% endblock %}
HTML

# accounts.html und settings.html bleiben weitgehend gleich, aber ich kopiere sie der Vollständigkeit halber rein, damit das Skript standalone funktioniert.
cat << 'HTML' > templates/accounts.html
{% extends "layout.html" %}
{% block content %}
<div class="row g-4">
  <div class="col-md-7">
    <div class="card h-100">
      <div class="card-header bg-transparent border-0 pt-4 px-4">
        <h5 class="mb-0 fw-bold">Gespeicherte Accounts</h5>
      </div>
      <div class="card-body p-0">
        <ul class="list-group list-group-flush">
          {% for acc in accounts %}
          <li class="list-group-item bg-transparent text-light d-flex justify-content-between align-items-center py-3 px-4 border-secondary border-opacity-25">
            <div class="d-flex align-items-center">
                <div class="bg-primary bg-opacity-10 rounded-circle d-flex align-items-center justify-content-center me-3" style="width:40px; height:40px;">
                    <i class="bi bi-person-fill h5 m-0 text-primary"></i>
                </div>
                <div>
                    <div class="fw-bold">{{ acc.email }}</div>
                    <div class="small text-muted">Aktiv</div>
                </div>
            </div>
            <a href="/accounts/delete/{{ loop.index0 }}" class="btn btn-sm btn-outline-danger border-0" onclick="return confirm('Account entfernen?')"><i class="bi bi-trash"></i></a>
          </li>
          {% else %}
          <li class="list-group-item bg-transparent text-muted text-center py-5">Keine Accounts hinterlegt.</li>
          {% endfor %}
        </ul>
      </div>
    </div>
  </div>
  <div class="col-md-5">
    <div class="card border-primary border-opacity-25 h-100">
      <div class="card-header bg-primary bg-opacity-10 text-primary fw-bold pt-3 px-3">
        <i class="bi bi-person-plus-fill me-2"></i> Account hinzufügen
      </div>
      <div class="card-body p-4">
        <form method="POST">
          <div class="mb-3">
            <label class="form-label text-muted small fw-bold">E-MAIL (Edu-ID)</label>
            <input type="email" name="email" class="form-control" required>
          </div>
          <div class="mb-4">
            <label class="form-label text-muted small fw-bold">PASSWORT</label>
            <input type="password" name="password" class="form-control" required>
          </div>
          <button type="submit" class="btn btn-primary w-100">Speichern</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
HTML

cat << 'HTML' > templates/settings.html
{% extends "layout.html" %}
{% block content %}
<div class="row justify-content-center mt-5">
  <div class="col-md-6 col-lg-5">
    <div class="card border-warning border-opacity-25 shadow-lg">
      <div class="card-header bg-warning bg-opacity-10 text-warning fw-bold text-center py-3">
        <i class="bi bi-key-fill me-2"></i> Web-Passwort ändern
      </div>
      <div class="card-body p-4">
        <form method="POST">
          <div class="mb-3">
             <label class="form-label text-muted small fw-bold">AKTUELLES PASSWORT</label>
            <input type="password" name="current_pw" class="form-control" required>
          </div>
          <hr class="border-secondary border-opacity-25 my-4">
          <div class="mb-3">
            <label class="form-label text-muted small fw-bold">NEUES PASSWORT</label>
            <input type="password" name="new_pw" class="form-control" required>
          </div>
          <div class="mb-4">
            <label class="form-label text-muted small fw-bold">WIEDERHOLEN</label>
            <input type="password" name="confirm_pw" class="form-control" required>
          </div>
          <button type="submit" class="btn btn-warning w-100 fw-bold text-dark">Ändern & Logout</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
HTML

echo "[INSTALL] Templates v2 erstellt."

# --- 6. Flask App (mit API für Logs & Kategorie-Fix) ---
cat << 'PYTHON' > app.py
import os
import threading
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from dotenv import load_dotenv, set_key

# Import Core Logic
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from roombooker.utils import smart_parse_date, smart_parse_time
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

# --- ROUTES ---

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
    cats = sm.get_categories() # Lade Kategorien direkt
    jm = JobManager()
    # Kategorien debuggen, falls leer
    if not cats:
        print("[DEBUG] Warnung: categories.json scheint leer oder nicht lesbar.")
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
        flash(f'Buchung für {date_str} gestartet! Siehe Logs.', 'success')
        # Starte im Hintergrund
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
    return render_template('logs.html')

@app.route('/api/logs')
@login_required
def api_logs():
    """Gibt Logs als Text zurück für AJAX/Polling"""
    lines = request.args.get('lines', default=200, type=int)
    log_content = ""
    try:
        if os.path.exists("log.txt"):
            with open("log.txt", "r") as f: 
                all_lines = f.readlines()
                log_content = "".join(all_lines[-lines:])
        else:
            log_content = "Warte auf Log-Datei..."
    except: 
        log_content = "Fehler beim Lesen."
    return log_content

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
            flash('Passwort geändert. Bitte neu einloggen.', 'success')
            return redirect(url_for('logout'))
            
    return render_template('settings.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
PYTHON
echo "[INSTALL] Flask App aktualisiert."

# --- 7. Docker neu bauen ---
echo "[INSTALL] Starte Docker Container neu..."
docker-compose down --remove-orphans
docker-compose up -d --build

echo ""
echo "=========================================================="
echo "   UPDATE ABGESCHLOSSEN - V2 "
echo "=========================================================="
echo "1. Warte ca. 10 Sekunden."
echo "2. Hole deinen NEUEN Link:"
echo "   docker-compose logs tunnel | grep trycloudflare.com"
echo ""
echo "Das Design ist jetzt 'polished' & responsiv."
echo "=========================================================="
