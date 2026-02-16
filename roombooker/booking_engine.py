import random
from .browser import BrowserEngine, parse_html_grid
from .intelligence import Intelligence
from .storage import StorageManager
from .config import HISTORY_FILE, CREDENTIALS_FILE, get_excessive_logging
from .utils import normalize_date_str

MAX_BOOKING_MINUTES = 240  # 4 h per account per day


class BookingEngine:
    def __init__(self, base_dir, max_attempts_per_gap=10):
        self.base_dir = base_dir
        self.intelligence = Intelligence()
        self.browser = BrowserEngine(headless=True)
        self.sm = StorageManager()
        self.max_attempts_per_gap = max_attempts_per_gap

    # ── helpers ──────────────────────────────────────────────

    def _check_room_available(self, availability, room, gap_start, gap_end):
        for fs, fe in availability.get(room, []):
            if fs <= gap_start and fe >= gap_end:
                return True
        return False

    def _calendar_sync_booking(self, booking_id, date_str, room, start_m, end_m,
                               email, category_key, job_id):
        """Push confirmed booking to Google Calendar."""
        try:
            if CREDENTIALS_FILE.exists():
                from .calendar_sync import CalendarSync
                cal = CalendarSync()
                cal.sync_booking(booking_id, date_str, room, start_m, end_m,
                                 email, category_key, job_id)
        except Exception as e:
            print(f"[ENGINE] Calendar-Sync fehlgeschlagen: {e}")

    def _split_gaps(self, gaps):
        """Split gaps that exceed MAX_BOOKING_MINUTES into smaller chunks."""
        out = []
        for g_s, g_e in gaps:
            while g_s < g_e:
                chunk_end = min(g_s + MAX_BOOKING_MINUTES, g_e)
                out.append((g_s, chunk_end))
                g_s = chunk_end
        return out

    def _sort_accounts_by_adjacency(self, accounts, gap_start, gap_end,
                                     date_str, history):
        """Sort accounts so that the best candidate is tried first.

        Priority order:
        1. Account that has an adjacent booking ending at gap_start or
           starting at gap_end (same room chain - can extend).
        2. Accounts with the LEAST used time today (spread load evenly +
           reduce chance of hitting 4h cap later).
        3. Random tiebreak among equals.
        """
        day_bookings = history.get(date_str, [])
        adjacent_emails = set()
        for b in day_bookings:
            bs, be = int(b['start']), int(b['end'])
            if be == gap_start or bs == gap_end:
                adjacent_emails.add(b.get('account', ''))

        email_minutes = {}
        for b in day_bookings:
            email = b.get('account', '')
            email_minutes[email] = email_minutes.get(email, 0) + (int(b['end']) - int(b['start']))

        def sort_key(acc):
            email = acc['email']
            is_adjacent = email in adjacent_emails
            used = email_minutes.get(email, 0)
            # Sort: adjacent first (False < True, so negate), then least used
            return (not is_adjacent, used, random.random())

        return sorted(accounts, key=sort_key)

    # ── main booking chain ───────────────────────────────────

    def book_chain(self, date_str, start_t, end_t, target_rooms,
                   category_key="default", job_id=None):
        date_str = normalize_date_str(date_str)
        history = self.sm._load(HISTORY_FILE, {})

        # ── Gaps berechnen ──
        gaps = self.intelligence.calculate_needed_slots(start_t, end_t, date_str, history)
        if not gaps:
            print(f"[ENGINE] Keine Luecken fuer {date_str}. Alles erledigt.")
            return True

        # Split gaps > 4 h (website limit per reservation)
        gaps = self._split_gaps(gaps)
        print(f"[ENGINE] Gaps: {[f'{s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d}' for s, e in gaps]}")

        # ── Continuity: rooms from earlier bookings today ──
        day_bookings = history.get(date_str, [])
        continuity_rooms = set()
        for b in day_bookings:
            r = b.get('room', '')
            if r and r not in target_rooms:
                continuity_rooms.add(r)
        all_rooms = list(target_rooms) + list(continuity_rooms)
        if continuity_rooms:
            print(f"[ENGINE] Kontinuität: + {continuity_rooms}")

        # ── Pre-scan grid ──
        availability = {}
        opening_hours = None
        try:
            grid_data, opening_hours = self.browser.scan_grid(date_str, all_rooms)
            total_evts = sum(len(v) for v in grid_data.values())
            print(f"[ENGINE] Grid gescannt -- {total_evts} Buchungen")

            if opening_hours:
                oh_s, oh_e = opening_hours
                for room in all_rooms:
                    booked = sorted(grid_data.get(room, []), key=lambda b: b['start'])
                    free, cursor = [], oh_s
                    for bk in booked:
                        if bk['start'] > cursor:
                            free.append((cursor, bk['start']))
                        cursor = max(cursor, bk['end'])
                    if cursor < oh_e:
                        free.append((cursor, oh_e))
                    availability[room] = free

                for room in all_rooms:
                    fr = availability.get(room, [])
                    if fr:
                        slots = ", ".join(f"{s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d}" for s, e in fr)
                        print(f"     [AVAIL] {room}: frei {slots}")
                    else:
                        print(f"     [AVAIL] {room}: komplett belegt")
        except Exception as e:
            print(f"[ENGINE] Grid-Scan fehlgeschlagen: {e} -- buche blind")

        if get_excessive_logging():
            self.intelligence.print_ascii_grid(date_str, history, opening_hours)

        # ── Account tracking ──
        # We do NOT exclude accounts just because they already booked today.
        # Instead, we rely on the 4-hour cap per account and prioritize
        # accounts intelligently based on adjacency and remaining capacity.

        all_ok = True
        for g_s, g_e in gaps:
            gap_dur = g_e - g_s

            # Score rooms
            scored = []
            for r in all_rooms:
                if availability and not self._check_room_available(availability, r, g_s, g_e):
                    if get_excessive_logging():
                        print(f"     [SKIP] {r}: kein Platz für {g_s//60:02d}:{g_s%60:02d}-{g_e//60:02d}:{g_e%60:02d}")
                    continue
                sc = self.intelligence.score_room(r, g_s, g_e, date_str, history)
                in_target = r in target_rooms
                scored.append({"name": r, "score": sc, "in_target": in_target})

            if not scored:
                print(f"[ENGINE] Gap {g_s//60:02d}:{g_s%60:02d}-{g_e//60:02d}:{g_e%60:02d}: alle belegt")
                all_ok = False
                continue

            scored.sort(key=lambda x: x['score'], reverse=True)

            # Warn if best room is from a different (smaller) category
            best = scored[0]
            if not best['in_target']:
                best_size = self.sm.get_room_category_size(best['name'])
                wanted_sizes = [self.sm.get_room_category_size(r) for r in target_rooms[:3]]
                wanted_max = max(wanted_sizes) if wanted_sizes else 0
                if best_size < wanted_max:
                    print(f"[ENGINE] Kontinuitaet: {best['name']} ist kleiner als gewuenschte Kategorie!")
                else:
                    print(f"[ENGINE] Kontinuitaet: {best['name']} (andere Kategorie)")

            print(f"[ENGINE] Gap {g_s//60:02d}:{g_s%60:02d}-{g_e//60:02d}:{g_e%60:02d}: "
                  f"{len(scored)} Raeume verfuegbar")

            # Filter accounts by 4-hour cap only (not by "already used today")
            accounts = self.sm.get_settings()
            active_accs = [a for a in accounts if a.get('active', True)]

            final_accs = []
            for a in active_accs:
                used_m = self.sm.get_account_minutes_on_date(date_str, a['email'])
                if used_m + gap_dur <= MAX_BOOKING_MINUTES:
                    final_accs.append(a)
                elif get_excessive_logging():
                    print(f"     [SKIP] {a['email']}: {used_m}min + {gap_dur}min > {MAX_BOOKING_MINUTES}min")

            if not final_accs:
                print(f"[ENGINE] Kein Account hat genug Restzeit fuer {gap_dur}min")
                all_ok = False
                continue

            # Smart account ordering: prefer accounts that are adjacent in time
            # (i.e., the account that booked the slot right before or after this gap)
            final_accs = self._sort_accounts_by_adjacency(
                final_accs, g_s, g_e, date_str, history
            )

            gap_filled = False
            attempts = 0
            max_att = min(self.max_attempts_per_gap, len(scored) * len(final_accs))

            for r_info in scored:
                if gap_filled or attempts >= max_att:
                    break
                r_name = r_info['name']
                for acc in final_accs:
                    if gap_filled or attempts >= max_att:
                        break
                    attempts += 1
                    print(f"[ENGINE] {g_s//60:02d}:{g_s%60:02d}-{g_e//60:02d}:{g_e%60:02d}: "
                          f"{r_name} (Score:{r_info['score']:.2f}) mit {acc['email']} "
                          f"({attempts}/{max_att})")

                    if self.browser.perform_booking(date_str, r_name, g_s, g_e, acc):
                        bid = self.sm.add_to_history(
                            date_str, r_name, g_s, g_e,
                            acc['email'], category_key, job_id,
                        )
                        self._calendar_sync_booking(
                            bid, date_str, r_name, g_s, g_e,
                            acc['email'], category_key, job_id,
                        )
                        history = self.sm._load(HISTORY_FILE, {})
                        gap_filled = True
                        break

            if not gap_filled:
                print(f"[ENGINE] Gap {g_s//60:02d}:{g_s%60:02d}-{g_e//60:02d}:{g_e%60:02d} "
                      f"nach {attempts} Versuchen gescheitert")
                all_ok = False

        return all_ok
