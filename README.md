# RoomBooker

Automated room-booking system for [raumreservation.ub.unibe.ch](https://raumreservation.ub.unibe.ch) with a Flask web dashboard, Playwright browser automation, Google Calendar integration, and a recurring job scheduler.

## Features

### Booking engine
- **Automatic gap splitting** -- a long booking (e.g. 10:00-21:00) is split into max-4-hour gaps, each booked with a different account to stay within the site's per-user limit.
- **Room scoring** -- rooms are ranked by availability, distance and historical weight. The best room is picked automatically.
- **Account rotation** -- accounts are cycled so no single user gets flagged.
- **14-day booking window** -- the booking site only allows reservations up to 14 days ahead. The scheduler waits until a date enters this window before booking.

### Room categories
- Rooms are grouped into user-defined categories (**large**, **medium**, **small**, **default**).
- Categories are managed via the web UI at `/categories`.
- Each job targets a specific category, so the engine only considers rooms in that group.

### Overlap detection (6 options)
When a new booking overlaps with existing bookings from a **different** category, the system offers 6 resolution options:

| # | Option | Behaviour |
|---|--------|-----------|
| 1 | **Ueberspringen** | Don't book, keep existing bookings |
| 2 | **Ersetzen & Erweitern** | Delete existing, book the combined time window |
| 3 | **Trotzdem buchen** | Book anyway, accept the overlap |
| 4 | **In bestehender Kategorie buchen** | Book new time range but in the existing category |
| 5 | **Anpassen (freie Teile)** | Only book segments that don't conflict |
| 6 | **Loeschen & nur B buchen** | Delete existing, book only the new range |

Same-category bookings are never flagged as overlaps.

### Recurring jobs & scheduler
- Jobs can be **once**, **daily**, **weekly**, **monthly**, or **custom** (every N days/weeks).
- The scheduler runs **daily at 00:15** and **hourly** to check which jobs have a `target_date` inside the 14-day window.
- After a booking succeeds, `target_date` advances to the next occurrence.
- Jobs can be toggled active/inactive or deleted from the web UI.

### Google Calendar sync
- Every booking is reflected as a Google Calendar event (service account).
- Pending jobs get **placeholder events** (up to 35 days ahead, marked as `Frei`/transparent).
- When a booking succeeds, the placeholder is updated with the actual room name, time, and status `booked`.
- On startup, `fix_all_existing_events()` normalises address and transparency on all future events.

### Web dashboard
| Route | Purpose |
|-------|---------|
| `/` | Dashboard with booking form and live status |
| `/jobs` | View, toggle, delete recurring jobs |
| `/categories` | Manage room categories |
| `/accounts` | Add / remove booking accounts |
| `/settings` | General settings |
| `/logs` | Live application logs |
| `/sync` | Trigger a real-time scan of all accounts |
| `/api/status` | JSON status endpoint |
| `/api/logs` | JSON log endpoint |

### CLI
`python3 cli.py` launches an interactive wizard to create bookings and jobs with the same overlap-detection logic as the web UI.

---

## Project structure

```
app.py                  Flask entrypoint, scheduler, all routes
main.py                 Booking orchestration (called by scheduler)
cli.py                  Interactive CLI wizard

roombooker/
  config.py             Paths and settings
  jobs.py               Job CRUD, recurrence advancement
  booking_engine.py     Gap calculation, room scoring, booking loop
  browser.py            Playwright login, grid scan, booking, deletion
  storage.py            JSON file I/O
  calendar_sync.py      Google Calendar create / update / delete
  utils.py              Date parsing, overlap detection, option builder
  intelligence.py       Room distance matrix, scoring weights
  models.py             Data models
  mqtt_notifier.py      Optional MQTT notifications
  categories.json       Default category definitions

templates/              Jinja2 templates (index, jobs, overlap, ...)
static/                 CSS, JS assets
```

### Data directory (outside repo)
Runtime data lives at `/home/leandro/auto_reserve_data` (override with `ROOMBOOKER_DATA_DIR`):
- `jobs.json` -- active job definitions
- `booking_history.json` -- per-date booking records
- `categories.json` -- room category definitions
- `settings.json` -- account credentials
- `google_credentials.json` -- service account key
- `rooms.json`, `weights.json`, `roomDistanceMatrix.json` -- scoring data
- `logs/` -- application logs
- `debug_scans/`, `debug_dumps/` -- HTML/screenshot debug artefacts

---

## Quick start

### Docker Compose (recommended)
```bash
docker compose up -d --build
```
The app runs on port **5000**. Source is volume-mounted so code changes take effect after `docker compose restart app`.

### Local
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python3 app.py
```

---

## Environment
- Python 3.10+, Flask, APScheduler, Playwright (Chromium)
- Docker container: `roombooker_app`
- Reverse proxy: Caddy + Cloudflare Tunnel (optional)

## Notes
- All credentials belong in the data directory, not in the repository.
- The booking site limits one reservation per user per day; the engine works around this by rotating accounts.
- Overlap detection only fires across **different** categories. If you book a new slot in the same category as existing bookings, no conflict is raised.
