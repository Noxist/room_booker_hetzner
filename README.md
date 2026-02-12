# Room Booker (Hetzner)

This repository contains an automated room-booking application with:
- a Flask web dashboard,
- booking/sync automation logic,
- persistent JSON-based data storage,
- and optional Cloudflare Tunnel exposure.

## Repository structure

### Core application
- `app.py` — Flask dashboard entrypoint (web routes/UI).
- `main.py` — orchestration for booking logic and calendar sync.
- `auto_booker.py` — booking helper script.
- `job_manager.py` — scheduler/job execution helper.
- `cli.py` — command-line entrypoint.

### Package: `roombooker/`
- `roombooker/config.py` — central paths/configuration (including data directory resolution).
- `roombooker/jobs.py` — job persistence and recurrence handling.
- `roombooker/booking_engine.py` — booking workflow engine.
- `roombooker/browser.py` — browser automation interactions.
- `roombooker/storage.py` — JSON storage abstraction.
- `roombooker/calendar_sync.py` / `roombooker/calendar.py` — calendar sync integration.
- `roombooker/models.py`, `roombooker/utils.py`, `roombooker/intelligence.py`, `roombooker/mqtt_notifier.py`, `roombooker/server_logger.py`, `roombooker/installer.py` — supporting modules.
- `roombooker/categories.json` — package-level category defaults.

### Web UI
- `templates/` — Jinja templates for dashboard pages.
- `static/css/style.css` — custom styling.
- `assets/icons/` — icon assets and notes.

### Runtime & deployment
- `Dockerfile` — app image build.
- `docker-compose.yml` — app + cloudflared tunnel stack.
- `requirements.txt` — Python dependencies.
- `booker_launcher.sh` — launcher helper.

### Data directory (outside repo)
The runtime data is expected at:
- `/home/leandro/auto_reserve_data`

Typical files there include:
- `jobs.json`, `settings.json`, `categories.json`, `rooms.json`,
- `booking_history.json`, `weights.json`, `google_credentials.json`,
- `last_scan.json`, `web_status.txt`.

You can override the data path using:
- `ROOMBOOKER_DATA_DIR=/your/path`

## Quick start

### Local
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

### Docker Compose
```bash
docker compose up -d --build
```

This starts:
- `app` on port `5000`
- `tunnel` (cloudflared) forwarding to `http://app:5000`

## Notes
- Keep secrets/credentials in the data directory, not in the repository.
- The app now consistently uses `ROOMBOOKER_DATA_DIR` when provided, to keep host + container paths aligned.
