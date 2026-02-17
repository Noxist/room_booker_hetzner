#!/usr/bin/env python3
"""
Simulation: Tests overlap detection and calendar merging logic
without performing any real bookings.
"""
import sys
import os
import json
from datetime import datetime, timedelta
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from roombooker.intelligence import Intelligence
from roombooker.utils import parse_time_to_minutes, format_minutes_to_time, check_overlap


def print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def simulate_merge_description(bookings):
    """Simulate the merged calendar event description."""
    lines = []
    for b in sorted(bookings, key=lambda x: x['start']):
        s = format_minutes_to_time(b['start'])
        e = format_minutes_to_time(b['end'])
        lines.append(f"{s}-{e}: {b['room']} ({b['account']})")
    return '\n'.join(lines)


def test_gap_calculation():
    """Test: detect gaps when partial bookings exist."""
    print_header("TEST 1: Gap-Berechnung mit bestehenden Buchungen")

    intel = Intelligence()
    history = {
        "26.02.2026": [
            {"room": "A-206", "start": 600, "end": 840,
             "account": "leandro@gmx.ch", "category": "medium"},
            {"room": "A-206", "start": 840, "end": 1080,
             "account": "christian@gmx.ch", "category": "medium"},
        ]
    }

    # Job wants 10:00-21:00 (600-1260)
    gaps = intel.calculate_needed_slots("10:00", "21:00", "26.02.2026", history)
    print(f"  Bestehend: 10:00-14:00, 14:00-18:00")
    print(f"  Gewuenscht: 10:00-21:00")
    print(f"  Gaps: {[(format_minutes_to_time(s), format_minutes_to_time(e)) for s, e in gaps]}")
    assert len(gaps) == 1, f"Expected 1 gap, got {len(gaps)}"
    assert gaps[0] == (1080, 1260), f"Expected (1080, 1260), got {gaps[0]}"
    print("  -> PASS: Nur 18:00-21:00 muss noch gebucht werden")


def test_overlap_detection():
    """Test: detect booking overlap between categories."""
    print_header("TEST 2: Overlap-Erkennung zwischen Kategorien")

    # Simulate: medium booking 10:00-21:00, user wants large 08:00-12:00
    from unittest.mock import patch, MagicMock

    mock_history = {
        "02.03.2026": [
            {"room": "A-206", "start": 600, "end": 840,
             "account": "saredi@gmail.com", "category": "medium"},
            {"room": "A-206", "start": 840, "end": 1080,
             "account": "leandro@gmx.ch", "category": "medium"},
        ]
    }

    # check_overlap looks at history from StorageManager
    with patch('roombooker.storage.StorageManager') as MockSM:
        sm_instance = MagicMock()
        sm_instance.get_history.return_value = mock_history
        MockSM.return_value = sm_instance

        overlaps = check_overlap("02.03.2026", "08:00", "12:00", "large")
        print(f"  Medium-Buchung: 10:00-18:00 in A-206")
        print(f"  Neue Anfrage: 08:00-12:00 in large")
        print(f"  Overlaps gefunden: {len(overlaps)}")
        for o in overlaps:
            s = format_minutes_to_time(o['start'])
            e = format_minutes_to_time(o['end'])
            print(f"    {s}-{e} ({o['category']})")
        assert len(overlaps) == 1, f"Expected 1 overlap, got {len(overlaps)}"
        print("  -> PASS: Overlap korrekt erkannt")


def test_same_category_no_overlap():
    """Test: same category bookings don't trigger overlap."""
    print_header("TEST 3: Gleiche Kategorie = kein Overlap-Alarm")

    from unittest.mock import patch, MagicMock

    mock_history = {
        "02.03.2026": [
            {"room": "A-206", "start": 600, "end": 840,
             "account": "leandro@gmx.ch", "category": "medium"},
        ]
    }

    with patch('roombooker.storage.StorageManager') as MockSM:
        sm_instance = MagicMock()
        sm_instance.get_history.return_value = mock_history
        MockSM.return_value = sm_instance

        overlaps = check_overlap("02.03.2026", "10:00", "21:00", "medium")
        print(f"  Bestehend: 10:00-14:00 medium")
        print(f"  Neu: 10:00-21:00 medium")
        print(f"  Overlaps: {len(overlaps)}")
        assert len(overlaps) == 0, f"Expected 0 overlaps (same category), got {len(overlaps)}"
        print("  -> PASS: Gleiche Kategorie loest keinen Alarm aus")


def test_calendar_merge_description():
    """Test: merged calendar event description format."""
    print_header("TEST 4: Kalender-Event Merge Beschreibung")

    bookings = [
        {"room": "A-206", "start": 600, "end": 840, "account": "leandro@gmx.ch"},
        {"room": "A-206", "start": 840, "end": 1080, "account": "christian@gmx.ch"},
        {"room": "A-206", "start": 1080, "end": 1260, "account": "saredi@gmail.com"},
    ]

    desc = simulate_merge_description(bookings)
    expected_lines = [
        "10:00-14:00: A-206 (leandro@gmx.ch)",
        "14:00-18:00: A-206 (christian@gmx.ch)",
        "18:00-21:00: A-206 (saredi@gmail.com)",
    ]
    print(f"  Beschreibung:\n{desc}")
    for line in expected_lines:
        assert line in desc, f"Missing: {line}"
    print("  -> PASS: Beschreibung korrekt formatiert")


def test_account_usage_tracking():
    """Test: track which accounts are used on a date."""
    print_header("TEST 5: Account-Nutzung pro Tag")

    history = {
        "02.03.2026": [
            {"room": "A-206", "start": 600, "end": 840,
             "account": "saredi@gmail.com", "category": "medium", "job_id": "46539fbe"},
            {"room": "A-206", "start": 840, "end": 1080,
             "account": "leandro@gmx.ch", "category": "medium", "job_id": "46539fbe"},
            {"room": "A-206", "start": 1080, "end": 1260,
             "account": "leandro77@gmail.com", "category": "medium", "job_id": "46539fbe"},
        ]
    }

    used = set(b.get('account', '') for b in history.get("02.03.2026", []))
    print(f"  Verwendete Accounts: {used}")
    assert "saredi@gmail.com" in used
    assert "leandro@gmx.ch" in used
    assert "leandro77@gmail.com" in used

    all_accounts = {"saredi@gmail.com", "leandro@gmx.ch", "leandro77@gmail.com", "christian@gmx.ch"}
    available = all_accounts - used
    print(f"  Noch verfuegbar: {available}")
    assert "christian@gmx.ch" in available
    print("  -> PASS: Account-Tracking funktioniert korrekt")


def test_two_jobs_same_day():
    """Test: two jobs targeting the same day don't create duplicate bookings."""
    print_header("TEST 6: Zwei Jobs am gleichen Tag (Overlap-Merge)")

    intel = Intelligence()

    # Job A already booked 10:00-21:00
    history = {
        "09.03.2026": [
            {"room": "A-206", "start": 600, "end": 840,
             "account": "leandro@gmx.ch", "category": "medium", "job_id": "46539fbe"},
            {"room": "A-206", "start": 840, "end": 1080,
             "account": "christian@gmx.ch", "category": "medium", "job_id": "46539fbe"},
            {"room": "A-206", "start": 1080, "end": 1260,
             "account": "saredi@gmail.com", "category": "medium", "job_id": "46539fbe"},
        ]
    }

    # Job B tries 10:00-21:00 on same day
    gaps = intel.calculate_needed_slots("10:00", "21:00", "09.03.2026", history)
    print(f"  Job A hat bereits 10:00-21:00 gebucht")
    print(f"  Job B will auch 10:00-21:00")
    print(f"  Gaps fuer Job B: {gaps}")
    assert len(gaps) == 0, f"Expected 0 gaps (fully covered), got {len(gaps)}"
    print("  -> PASS: Job B erkennt, dass alles bereits abgedeckt ist")


def test_split_gaps():
    """Test: gaps exceeding 4h are split correctly."""
    print_header("TEST 7: Gap-Splitting bei >4h")

    from roombooker.booking_engine import BookingEngine
    # We only test _split_gaps, no browser needed
    engine = BookingEngine.__new__(BookingEngine)

    gaps = [(600, 1260)]  # 10:00-21:00 = 11h
    split = engine._split_gaps(gaps)
    print(f"  Input: 10:00-21:00 (660min)")
    print(f"  Split: {[(format_minutes_to_time(s), format_minutes_to_time(e)) for s, e in split]}")
    assert len(split) == 3, f"Expected 3 chunks, got {len(split)}"
    assert split[0] == (600, 840), f"Chunk 1: expected (600,840), got {split[0]}"
    assert split[1] == (840, 1080), f"Chunk 2: expected (840,1080), got {split[1]}"
    assert split[2] == (1080, 1260), f"Chunk 3: expected (1080,1260), got {split[2]}"
    print("  -> PASS: 11h korrekt in 4h+4h+3h aufgeteilt")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("  ROOMBOOKER OVERLAP SIMULATION")
    print("  Datum: " + datetime.now().strftime("%d.%m.%Y %H:%M"))
    print("  KEIN echtes Buchen - nur Logik-Tests")
    print("="*70)

    tests = [
        test_gap_calculation,
        test_overlap_detection,
        test_same_category_no_overlap,
        test_calendar_merge_description,
        test_account_usage_tracking,
        test_two_jobs_same_day,
        test_split_gaps,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  -> FAIL: {e}")
            failed += 1

    print(f"\n{'='*70}")
    print(f"  ERGEBNIS: {passed}/{passed+failed} Tests bestanden")
    if failed:
        print(f"  {failed} Tests fehlgeschlagen!")
    else:
        print("  Alle Tests bestanden!")
    print(f"{'='*70}\n")
