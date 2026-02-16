#!/usr/bin/env python3
"""
One-time script: Delete all bookings AFTER 17.02.2026 from the vonRoll website
and clean local data files (jobs.json, last_scan.json, booking_history.json).
Uses batch deletion -- one login per account for all its deletions.
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from roombooker.storage import StorageManager
from roombooker.browser import BrowserEngine
from roombooker.config import HISTORY_FILE, JOBS_FILE, BASE_DIR

CUTOFF = datetime(2026, 2, 17, 23, 59, 59)  # keep 17.02 and earlier


def main():
    sm = StorageManager()
    history = sm.get_history()
    accounts = sm.get_settings()
    acc_map = {a['email']: a for a in accounts}

    # Collect bookings to delete from website (after 17.02)
    to_delete = []  # (date_str, start_m, end_m, email)
    for date_str, bookings in history.items():
        try:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
        except Exception:
            continue
        if dt > CUTOFF:
            for b in bookings:
                email = b.get('account', '')
                if email in acc_map:
                    to_delete.append((date_str, int(b['start']), int(b['end']), email))

    if not to_delete:
        print("[CLEANUP] No bookings after 17.02.2026 found in history.")
    else:
        print(f"[CLEANUP] Found {len(to_delete)} bookings after 17.02.2026 to delete:")
        for d, s, e, email in to_delete:
            print(f"  {d} {s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d} ({email})")

        confirm = input("\nDelete these from the vonRoll website? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Aborted.")
            return

        # Group by account for batch deletion (one login per account)
        by_account = {}
        for d, s, e, email in to_delete:
            by_account.setdefault(email, []).append((d, s, e))

        browser = BrowserEngine(headless=True)
        deleted = 0

        for email, items in by_account.items():
            print(f"\n--- Account: {email} ({len(items)} deletions, single login) ---")
            results = browser.delete_bookings_batch(items, acc_map[email])
            for i, (d, s, e) in enumerate(items):
                status = "OK" if results[i] else "FAILED"
                print(f"  {d} {s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d} -> {status}")
                if results[i]:
                    deleted += 1

        print(f"\n[CLEANUP] Deleted {deleted}/{len(to_delete)} from website.")

    # Clean local files
    print("\n[CLEANUP] Cleaning local data files...")

    # Remove bookings after 17.02 from history
    new_history = {}
    for date_str, bookings in history.items():
        try:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
        except Exception:
            continue
        if dt <= CUTOFF:
            new_history[date_str] = bookings
    sm.save_history(new_history)
    removed_dates = len(history) - len(new_history)
    print(f"  booking_history.json: removed {removed_dates} dates after 17.02")

    # Clear jobs.json
    jobs_path = BASE_DIR / "jobs.json"
    with open(jobs_path, "w") as f:
        json.dump([], f, indent=2)
    print("  jobs.json: cleared")

    # Clear last_scan.json
    scan_path = BASE_DIR / "last_scan.json"
    with open(scan_path, "w") as f:
        json.dump([], f, indent=2)
    print("  last_scan.json: cleared")

    print("\n[CLEANUP] Done! Ready for debugging.")


if __name__ == "__main__":
    main()
